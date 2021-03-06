import datetime
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import mail_managers, send_mail
from django.core.urlresolvers import reverse
from django.utils.text import slugify
from django.utils.translation import ugettext as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from services.rest.mixins import FieldValidationMixin
from services.rest.validators import DependedFieldsValidator
from shareholder.models import (Company, Country, Operator, OptionPlan,
                                OptionTransaction, Position, Security,
                                Shareholder, UserProfile)
from utils.formatters import string_list_to_json, inflate_segments
from utils.hashers import random_hash
from utils.math import substract_list
from utils.user import make_username

User = get_user_model()
logger = logging.getLogger(__name__)


class CountrySerializer(serializers.HyperlinkedModelSerializer):
    """ list of countries selectable """

    class Meta:
        model = Country
        fields = ('url', 'iso_code', 'name')


class SecuritySerializer(serializers.HyperlinkedModelSerializer,
                         FieldValidationMixin):
    readable_title = serializers.SerializerMethodField()
    readable_number_segments = serializers.SerializerMethodField()

    class Meta:
        model = Security
        fields = ('pk', 'readable_title', 'title', 'url', 'count',
                  'track_numbers', 'readable_number_segments',
                  'number_segments')

    def get_readable_title(self, obj):
        return obj.get_title_display()

    def get_readable_number_segments(self, obj):
        """
        change json into human readble format
        """
        return str(obj.number_segments).translate(None, "'[]u{}")

    def update(self, instance, validated_data):
        """
        handle saving human readable numbers segments format
        """
        number_segments = validated_data.get(
            'number_segments', instance.number_segments)
        instance.number_segments = number_segments
        instance.save()
        return instance


class CompanySerializer(serializers.HyperlinkedModelSerializer):
    security_set = SecuritySerializer(many=True, read_only=True)
    country = serializers.HyperlinkedRelatedField(
        view_name='country-detail',
        required=False,
        allow_null=True,
        queryset=Country.objects.all(),
    )
    founded_at = serializers.DateField()
    profile_url = serializers.SerializerMethodField()
    captable_pdf_url = serializers.SerializerMethodField()
    captable_csv_url = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = ('pk', 'name', 'share_count', 'country', 'url',
                  'shareholder_count', 'security_set', 'founded_at',
                  'provisioned_capital', 'profile_url', 'captable_pdf_url',
                  'captable_csv_url', 'logo_url')

    def get_profile_url(self, obj):
        return reverse('company', kwargs={'company_id': obj.id})

    def get_captable_pdf_url(self, obj):
        return reverse('captable_pdf', kwargs={'company_id': obj.id})

    def get_captable_csv_url(self, obj):
        return reverse('captable_csv', kwargs={'company_id': obj.id})

    def get_logo_url(self, obj):
        return obj.get_logo_url()


class AddCompanySerializer(serializers.Serializer):

    name = serializers.CharField(max_length=255)
    face_value = serializers.DecimalField(max_digits=19, decimal_places=4)
    founded_at = serializers.DateTimeField(required=False)
    count = serializers.IntegerField()

    def create(self, validated_data):
        """ check data, add company, add company_itself shareholder, add first
        position' """

        user = validated_data.get("user")
        company = Company.objects.create(
            share_count=validated_data.get("count"),
            name=validated_data.get("name"),
            founded_at=validated_data.get('founded_at')
        )
        security = Security.objects.create(
            title="C",
            count=validated_data.get("count"),
            company=company,
        )

        username = make_username('Company', 'itself', company.name)
        # user tried to add company already
        if User.objects.filter(username=username).exists():
            username = username[:25] + u'-' + random_hash(digits=4)

        # create company user
        companyuser = User.objects.create(
            username=username,
            first_name='Unternehmen:', last_name=company.name[:30],
            email='info+{}@darg.ch'.format(slugify(company.name))
        )
        shareholder = Shareholder.objects.create(user=companyuser,
                                                 company=company, number='0')
        Position.objects.create(
            bought_at=validated_data.get(
                'founded_at') or datetime.datetime.now(),
            buyer=shareholder, count=validated_data.get("count"),
            value=validated_data.get("face_value"),
            security=security,
        )
        Operator.objects.create(user=user, company=company)

        mail_managers(
            u'new user signed up',
            u'user {} signed up for company {}'.format(user, company)
        )

        return validated_data


class UserProfileSerializer(serializers.HyperlinkedModelSerializer):
    """ serialize additional user data """
    # country = CountrySerializer(many=False)
    readable_language = serializers.SerializerMethodField()
    birthday = serializers.DateTimeField(
        required=False, allow_null=True)

    class Meta:
        model = UserProfile
        fields = ('street', 'city', 'province', 'postal_code', 'country',
                  'birthday', 'company_name', 'language', 'readable_language')

    def get_readable_language(self, obj):
        return obj.get_language_display()


class UserWithEmailOnlySerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name')
        read_only_fields = ('first_name', 'last_name',)


class OperatorSerializer(serializers.HyperlinkedModelSerializer):
    # company = CompanySerializer(many=False, read_only=True)
    company = serializers.HyperlinkedRelatedField(
        many=False,
        read_only=False,
        view_name='company-detail',
        queryset=Company.objects.all(),
    )
    is_myself = serializers.SerializerMethodField()
    user = UserWithEmailOnlySerializer()

    class Meta:
        model = Operator
        fields = (
            'id',
            'company',
            'is_myself',
            'user',
        )

    def get_is_myself(self, obj):
        return obj.user == self.context.get("request").user

    def create(self, validated_data):
        """ create new operator """
        if User.objects.filter(
            email=validated_data.get('user').get('email')
        ).exists():
            user = User.objects.get(
                email=validated_data.get('user').get('email'))
        else:
            raise ValidationError({'email': _(
                'User not yet registered with this '
                'application. Please ask the user to register first.'
            )})
        company = validated_data.get('company')
        myself = self.context.get("request").user
        if not myself.operator_set.filter(company=company):
            raise ValidationError({'company': _(
                'You cannot edit this company'
            )})

        # notify
        send_mail(
            _('You were added as administrator for {}').format(company.name),
            _('Dear,\n\n'
              'you have been granted edit privileges for this '
              'company on the share register\n\nKind regards\n\n'
              'Your Das-Aktienregister Team'),
            settings.SERVER_EMAIL,
            [user.email], fail_silently=False)

        return Operator.objects.create(user=user, company=company)


class UserWithEmailOnlySerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = User
        fields = ('email',)


class UserSerializer(serializers.HyperlinkedModelSerializer):
    operator_set = OperatorSerializer(many=True, read_only=True)
    userprofile = UserProfileSerializer(
        many=False, required=False, allow_null=True)

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'operator_set',
                  'userprofile')

    def create(self, validated_data):

        if not validated_data.get('user').get('email'):
            raise ValidationError(_('Email missing'))

        if validated_data.get('user').get('userprofile'):
            userprofile_data = validated_data.pop('userprofile')
            userprofile = UserProfile.objects.create(**userprofile_data)
        else:
            raise ValidationError('Missing User Profile data')

        if validated_data.get('user').get('userprofile').get('country'):
            country_data = validated_data.get(
                'user').get('userprofile').get('country')
            country = Country.objects.create(**country_data)
        else:
            raise ValidationError('Missing country data')

        validated_data['user']['userprofile'] = userprofile
        validated_data['user']['userprofile']['country'] = country

        user = User.objects.create(**validated_data)

        return user


class ShareholderSerializer(serializers.HyperlinkedModelSerializer):
    user = UserSerializer(many=False)
    company = CompanySerializer(many=False,  read_only=True)
    is_company = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Shareholder
        fields = (
            'pk', 'user', 'number', 'company', 'share_percent', 'share_count',
            'share_value', 'validate_gafi', 'is_company', 'full_name'
        )

    def create(self, validated_data):

        # existing or new user
        user = self.context.get("request").user

        # FIXME: assuming one company per user
        company = user.operator_set.all()[0].company

        if not validated_data.get('user').get('email'):
            raise ValidationError({'email': [_('Email missing')]})

        if not validated_data.get('user').get('first_name'):
            raise ValidationError({'first_name': [_('First Name missing')]})

        if not validated_data.get('user').get('last_name'):
            raise ValidationError({'last_name': [_('Last Name missing')]})

        if company.shareholder_set.filter(
            number=validated_data.get('number')
        ).exists():
            raise ValidationError(
                {'number': [_('Shareholder Number must be unique')]})

        # get unique username
        username = make_username(
            validated_data.get("user").get("first_name") or '',
            validated_data.get("user").get("last_name") or '',
            validated_data.get("user").get("email") or ''
        )

        shareholder_user, created = User.objects.get_or_create(
            email=validated_data.get("user").get("email"),
            defaults={
                "username": username,
                "first_name": validated_data.get("user").get("first_name"),
                "last_name": validated_data.get("user").get("last_name"),
            })

        if not hasattr(shareholder_user, 'userprofile'):
            shareholder_user.userprofile = UserProfile.objects.create()

        if not created:
            if not shareholder_user.first_name:
                shareholder_user.first_name = validated_data.get(
                    "user").get("first_name")
            if not shareholder_user.last_name:
                shareholder_user.last_name = validated_data.get(
                    "user").get("last_name")
            shareholder_user.save()

        # save shareholder
        shareholder, created = Shareholder.objects.get_or_create(
            user=shareholder_user,
            company=company,
            defaults={"number": validated_data.get("number")},
        )

        return shareholder

    def update(self, instance, validated_data):

        shareholder = instance
        user = shareholder.user

        # don't create duplicate users with same email
        if User.objects.get(email=validated_data['user']['email']) != user:
            raise ValidationError({'email': [_('This email is already taken by another user/shareholder.')]})

        user.email = validated_data['user']['email']
        user.first_name = validated_data['user']['first_name']
        user.last_name = validated_data['user']['last_name']
        user.save()

        profile_kwargs = validated_data['user']['userprofile']
        if not hasattr(user, 'userprofile'):
            userprofile = UserProfile.objects.create(**profile_kwargs)
            user.userprofile = userprofile
            user.save()
        else:
            userprofile = user.userprofile
            userprofile.street = profile_kwargs.get('street')
            userprofile.city = profile_kwargs.get('city')
            userprofile.province = profile_kwargs.get('province')
            userprofile.postal_code = profile_kwargs.get('postal_code')
            userprofile.country = profile_kwargs.get('country')
            userprofile.company_name = profile_kwargs.get('company_name')
            userprofile.birthday = profile_kwargs.get('birthday')
            userprofile.language = profile_kwargs.get('language')
            userprofile.save()

        shareholder.number = validated_data['number']
        shareholder.save()
        return shareholder

    def get_is_company(self, obj):
        """
        bool if shareholder is company itself
        """
        return obj.is_company_shareholder()

    def get_full_name(self, obj):
        return u"{} {}".format(obj.user.first_name, obj.user.last_name)


class PositionSerializer(serializers.HyperlinkedModelSerializer,
                         FieldValidationMixin):

    buyer = ShareholderSerializer(many=False, required=False)
    seller = ShareholderSerializer(many=False, required=False)
    security = SecuritySerializer(many=False, required=True)
    bought_at = serializers.DateTimeField()  # e.g. 2015-06-02T23:00:00.000Z
    readable_number_segments = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = (
            'pk', 'buyer', 'seller', 'bought_at', 'count', 'value',
            'security', 'comment', 'is_split', 'is_draft', 'number_segments',
            'readable_number_segments')
        validators = [DependedFieldsValidator(fields=('seller', 'buyer'))]

    def get_readable_number_segments(self, obj):
        """
        change json into human readble format
        """
        return str(obj.number_segments).translate(None, "'[]u{}")

    def is_valid(self, raise_exception=False):
        """
        validate cross data relations
        """

        logger.info('position create validation...')

        res = super(PositionSerializer, self).is_valid(raise_exception)

        initial_data = self.initial_data
        security = initial_data.get('security')
        user = self.context.get("request").user
        company = user.operator_set.all()[0].company

        if security and Security.objects.get(
                company=company, title=security.get('title')).track_numbers:

            logger.info('validation: prepare data...')
            security = Security.objects.get(id=security['pk'])
            if (isinstance(initial_data.get('number_segments'), str) or
                    isinstance(initial_data.get('number_segments'), unicode)):
                segments = string_list_to_json(
                    initial_data.get('number_segments'))
            else:
                segments = initial_data.get('number_segments')
            # if we have seller (non capital increase)
            if initial_data.get('seller'):
                logger.info('validation: get seller segments...')
                seller = Shareholder.objects.get(
                    pk=initial_data.get('seller')['pk'])
                owning, failed_segments, owned_segments = seller.owns_segments(
                    segments, security)
                logger.info(
                    'validation: seller segs {} for security {} done'.format(
                        segments, security))

            # we need number_segments if this is a security with .track_numbers
            if not segments:
                raise serializers.ValidationError(
                    {'number_segments':
                        [_('Invalid security numbers segments.')]})

            # segments must be owned by seller
            elif initial_data.get('seller') and not owning:
                raise serializers.ValidationError({
                    'number_segments':
                        [_('Segments "{}" must be owned by seller "{}". '
                           'Available are {}').format(
                              failed_segments, seller.user.last_name,
                              owned_segments
                        )]
                })

            # validate segment count == share count
            elif (security.count_in_segments(segments) !=
                    initial_data.get('count')):
                logger.info('validation: checking count...')
                raise serializers.ValidationError({
                    'count':
                        [_('Number of shares in segments ({}) '
                           'does not match count {}').format(
                                security.count_in_segments(segments),
                                initial_data.get('count')
                           )]
                })

            # segment must not be used by option plan
            logger.info('validation: option plan validation...')
            inflated_segments = inflate_segments(segments)
            oplan_segments = inflate_segments(
                security.company.get_all_option_plan_segments())
            if substract_list(
                inflated_segments, oplan_segments
            ) != inflated_segments:
                raise serializers.ValidationError({
                    'number_segments':
                        [_('Segment {} is blocked for options and cannot be'
                           ' transfered to a shareholder.').format(segments)]
                })

        return res

    def create(self, validated_data):
        """ adding a new position and handling nested data for buyer
        and seller """

        logger.info('position create ...')

        # prepare data
        kwargs = {}
        user = self.context.get("request").user
        company = user.operator_set.all()[0].company

        security = Security.objects.get(
            company=company,
            title=validated_data.get('security').get('title')
        )

        # regular security transaction
        if validated_data.get("seller") and validated_data.get("buyer"):
            buyer = Shareholder.objects.get(
                company=company,
                user__email=validated_data.get(
                    "buyer").get("user").get("email")
            )
            seller = Shareholder.objects.get(
                company=company,
                user__email=validated_data.get(
                    "seller").get("user").get("email")
            )
            kwargs.update({"seller": seller})

        # capital increase
        else:
            buyer = company.get_company_shareholder()
            company.share_count = company.share_count + \
                validated_data.get("count")

            # add new number segments to company register
            if security.track_numbers:
                segs = validated_data.get('number_segments')
                security.number_segments.extend(segs)
                security.save()

            company.save()

        kwargs.update({
            "buyer": buyer,
            "bought_at": validated_data.get("bought_at"),
            "value": validated_data.get("value"),
            "count": validated_data.get("count"),
            "security": security,
            "comment": validated_data.get("comment"),
        })

        # segments must be ordered, have no duplicates and must be list...
        if security.track_numbers and validated_data.get("number_segments"):
            kwargs.update({
                "number_segments": validated_data.get("number_segments")
            })

        position = Position.objects.create(**kwargs)

        return position


class OptionTransactionSerializer(serializers.HyperlinkedModelSerializer):
    buyer = ShareholderSerializer(many=False, required=True)
    seller = ShareholderSerializer(many=False, required=True)
    bought_at = serializers.DateField()  # e.g. 2015-06-02T23:00:00.000Z
    readable_number_segments = serializers.SerializerMethodField()

    class Meta:
        model = OptionTransaction
        fields = ('pk', 'buyer', 'seller', 'bought_at', 'count', 'option_plan',
                  'is_draft', 'number_segments', 'readable_number_segments')

    def is_valid(self, raise_exception=False):
        """
        validate cross data relations
        """
        res = super(OptionTransactionSerializer, self).is_valid(raise_exception)

        initial_data = self.initial_data

        option_plan = OptionPlan.objects.get(id=int(
            initial_data.get('option_plan').split('/')[-1]))
        security = option_plan.security

        if not security.track_numbers:
            return res

        if (isinstance(initial_data.get('number_segments'), str) or
                isinstance(initial_data.get('number_segments'), unicode)):
            segments = string_list_to_json(initial_data.get('number_segments'))
        else:
            segments = initial_data.get('number_segments')

        # we need number_segments if this is a security with .track_numbers
        if not segments:
            raise serializers.ValidationError(
                {'number_segments':
                    [_('Invalid security numbers segments.')]})

        # if we have seller (non capital increase)
        if initial_data.get('seller'):
            seller = Shareholder.objects.get(
                pk=initial_data.get('seller')['pk'])
            owning, failed_segments, owned_segments = seller.\
                owns_options_segments(segments, security)

        # segments must be owned by seller
        if initial_data.get('seller') and not owning:
            raise serializers.ValidationError({
                'number_segments':
                    [_('Segments "{}" must be owned by seller "{}". '
                       'Available are {}').format(
                          failed_segments, seller.user.last_name,
                          owned_segments
                    )]
            })

        # validate segment count == share count
        elif (security.count_in_segments(segments) !=
                initial_data.get('count')):
            raise serializers.ValidationError({
                'count':
                    [_('Number of shares in segments ({}) '
                       'does not match count {}').format(
                            security.count_in_segments(segments),
                            initial_data.get('count')
                       )]
            })

        # segments must be inside option plans segments
        for segment in inflate_segments(segments):
            if segment not in inflate_segments(option_plan.number_segments):
                raise serializers.ValidationError({
                    'number_segments':
                        [_('Segment {} is not reserved for options inside a'
                           ' option plan and cannot be'
                           ' transfered to a option holder. Available are: '
                           '{}').format(segment, option_plan.number_segments)]
                })

        return res

    def create(self, validated_data):

        # prepare data
        kwargs = {}
        user = self.context.get("request").user
        company = user.operator_set.all()[0].company
        option_plan = validated_data.get('option_plan')

        buyer = Shareholder.objects.get(
            company=company,
            user__email=validated_data.get(
                "buyer").get("user").get("email")
        )
        seller = Shareholder.objects.get(
            company=company,
            user__email=validated_data.get(
                "seller").get("user").get("email")
        )
        kwargs.update({"seller": seller})
        kwargs.update({"buyer": buyer})

        kwargs.update({
            "bought_at": validated_data.get("bought_at"),
            "count": validated_data.get("count"),
            "option_plan": option_plan,
            "vesting_months": validated_data.get("vesting_months"),
        })

        # segments must be ordered, have no duplicates and must be list...
        if (option_plan.security.track_numbers and
                validated_data.get("number_segments")):

            kwargs.update({
                "number_segments": string_list_to_json(
                    validated_data.get("number_segments"))
            })

        option_transaction = OptionTransaction.objects.create(**kwargs)

        return option_transaction

    def get_readable_number_segments(self, obj):
        """
        change json into human readble format
        """
        return str(obj.number_segments).translate(None, "'[]u{}")


class OptionPlanSerializer(serializers.HyperlinkedModelSerializer):
    security = SecuritySerializer(many=False, required=True)
    optiontransaction_set = OptionTransactionSerializer(many=True,
                                                        read_only=True)
    board_approved_at = serializers.DateField()
    readable_number_segments = serializers.SerializerMethodField()

    class Meta:
        model = OptionPlan
        fields = ('pk', 'title', 'security', 'optiontransaction_set',
                  'exercise_price', 'count', 'comment', 'board_approved_at',
                  'url', 'pdf_file', 'pdf_file_preview_url', 'pdf_file_url',
                  'number_segments', 'readable_number_segments')

    def validate_pdf_file(self, value):
        if not value:
            return

        if value.content_type == 'application/pdf':
            return value
        else:
            raise serializers.ValidationError(_("Not a pdf file."))

    def create(self, validated_data):

        # prepare data
        kwargs = {}
        user = self.context.get("request").user
        company = user.operator_set.all()[0].company
        security = Security.objects.get(
            company=company,
            title=validated_data.get("security").get('title'))

        kwargs.update({
            "company": company,
            "board_approved_at": validated_data.get("board_approved_at"),
            "title": validated_data.get("title"),
            "security": security,
            "count": validated_data.get("count"),
            "exercise_price": validated_data.get("exercise_price"),
            "comment": validated_data.get("comment"),
        })

        # segments must be ordered, have no duplicates and must be list...
        if security.track_numbers and validated_data.get("number_segments"):
            kwargs.update({
                "number_segments": string_list_to_json(
                    validated_data.get("number_segments"))
            })

        option_plan = OptionPlan.objects.create(**kwargs)

        # assign all initial options to company shareholder
        cs = company.get_company_shareholder()
        kwargs = {
            'option_plan': option_plan,
            'bought_at': validated_data.get("board_approved_at"),
            'buyer': cs,
            'count': validated_data.get("count")
        }

        # segments must be ordered, have no duplicates and must be list...
        if security.track_numbers and validated_data.get("number_segments"):
            kwargs.update({
                "number_segments": string_list_to_json(
                    validated_data.get("number_segments"))
            })

        OptionTransaction.objects.create(**kwargs)

        return option_plan

    def get_readable_number_segments(self, obj):
        """
        change json into human readble format
        """
        return str(obj.number_segments).translate(None, "'[]u{}")

    def is_valid(self, raise_exception=False):
        """
        validate cross data relations
        """
        res = super(OptionPlanSerializer, self).is_valid(raise_exception)

        initial_data = self.initial_data

        security = initial_data.get('security')
        if security and Security.objects.get(id=security['pk']).track_numbers:

            security = Security.objects.get(id=security['pk'])
            if (isinstance(initial_data.get('number_segments'), str) or
                    isinstance(initial_data.get('number_segments'), unicode)):
                segments = string_list_to_json(
                    initial_data.get('number_segments'))
            else:
                segments = initial_data.get('number_segments')

            # we need number_segments if this is a security with .track_numbers
            if not segments:
                raise serializers.ValidationError(
                    {'number_segments':
                        [_('Invalid or empty security numbers segments.')]})

            # segments must be available by company shareholder
            cs = security.company.get_company_shareholder()
            owning, failed_segments, owned_segments = cs.owns_segments(
                    segments, security)

            # segments must be owned by seller
            if not owning:
                raise serializers.ValidationError({
                    'number_segments':
                        [_('Segments "{}" must be owned by company shareholder '
                           '"{}". Available are {}').format(
                              failed_segments, cs.user.last_name,
                              owned_segments
                        )]
                })

            # validate segment count == share count
            elif (security.count_in_segments(segments) !=
                    initial_data.get('count')):
                raise serializers.ValidationError({
                    'count':
                        [_('Number of shares in segments ({}) '
                           'does not match count {}').format(
                                security.count_in_segments(segments),
                                initial_data.get('count')
                           )]
                })

        return res


class OptionHolderSerializer(serializers.HyperlinkedModelSerializer):
    user = UserSerializer(many=False)
    company = CompanySerializer(many=False,  read_only=True)

    class Meta:
        model = Shareholder
        fields = (
            'pk', 'user', 'number', 'company', 'options_percent',
            'options_count', 'options_value'
        )
