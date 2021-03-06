Das Aktienregister.
==========================

Develop: [![Build Status](https://semaphoreci.com/api/v1/projects/e5b958e0-838d-4565-b8f5-4bea164a65ee/435885/badge.svg)](https://semaphoreci.com/vbnet/aktienregister)  

CapTable
===========================
This app provides an easy to user interface to have a simple CapTable (incl. options, ESOP etc.). Means enter company data, enter shareholders, have transactions for shareholders, print CapTable, edit company core data, enter capital increases. Supports a mulitple asset types for a company (named/registered share OR bearer share).

SetUp
===========================

For setup here is a copy of the build commands for latest `Ubuntu LTS`:
```
export DEBIAN_FRONTEND=noninteractive
export INSTAPAGE_TOKEN='REPLACEME'
export INSTAPAGE_ACCESS_TOKEN='REPLACEME'
export LC_ALL=en_US.UTF-8
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 1397BC53640DB551
sudo apt-get update
sudo apt-get -q -y install python-virtualenv python-dev google-chrome-stable firefox xvfb wamerican exim4
virtualenv .ve
source .ve/bin/activate
pip install -r requirements.txt
pip install -r requirements_ci.txt
sudo -u postgres psql -c "CREATE ROLE darg WITH password 'darg' LOGIN;" 
sudo -u postgres psql -c "ALTER ROLE darg WITH CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE darg WITH OWNER darg;"
python ./minify_static.py
cd site
cp project/settings/dev_local.dist.py project/settings/dev_local.py
python manage.py collectstatic --noinput --settings=project.settings.dev
```

Please also put latest chromedriver into `site` directory as executable. App should then be up and running.

See https://github.com/patroqueeet/darg/blob/develop/dev_commands.md for details about compiling etc. Make sure `bower` and `npm` installs in `darg.js` are being run befor development start.

Development Guidelines
=========================

Please work with pull requests (fork before). Every Pull request must contain:
* code change
  * maintain current code pattern (comments, code structure) - it should not be possible to see who coded what
  * use as much existing pattern as possible
  * must be production ready, there is no QA, we expect your code to work out of the box with all technical risk handled
  * don't add any technical debt. deliver perfect. do it now.
  * work with linting for all languages. if you improve existing code, make a separate commit for it
* tests (prefer fast unittests but make sure you cover the risk added by your code, in case of doubt add selenium based test).
* proper commit message (read http://chris.beams.io/posts/git-commit/)

Debugging:
* if a ticket reports a bug, write a failing test to reproduce the issue. then fix the issue and commit working test and fix at once.

Collab guidelines:
* ask before you code, if you don't you will fail and your pull request will be rejected

Recommended `.vimrc` for coding is:
```
" Pathogen load
filetype off

call pathogen#infect()
call pathogen#helptags()

filetype plugin indent on
syntax on

" http://stackoverflow.com/questions/1523482/vimrc-configuration-for-python
autocmd BufRead *.py set smartindent cinwords=if,elif,else,for,while,try,except,finally,def,class
set tabstop=4
set shiftwidth=4
set expandtab
set autoindent
set smartindent
syntax on
set listchars=tab:>-
set listchars+=trail:.
set ignorecase
set smartcase

" disable rope
let g:pymode_rope = 0
" ignore pep 8 errors
let g:pep8_ignore="E401"
let g:pymode_lint_config = '$HOME/pylint.rc'

" shortcuts
nmap j <Esc>:tabprev<CR>
nmap k <Esc>:tabnext<CR>
```
using plugins `python-mode`, `pathogen`, `vim-isort`.

Please note that `Isort` must handle the import formatting.

For debugging we replaced `pdb` with `pdb++` and also provide `FunctionalTestCase._screenshot()` and `FunctionalTestCase._handle_exception()` for Selenium Test debugging/failure handling.


Licence
-------------------------

This software is handled by GNU GENERAL PUBLIC LICENSE v2.0. Means most importantly all changes and additions must be shared publicly too.
