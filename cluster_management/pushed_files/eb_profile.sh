# .bashrc

# Source global definitions
if [ -f /etc/bashrc ]; then
	. /etc/bashrc
fi

# User specific aliases and functions

# load the current environment variables for the ssh session
source /opt/python/current/env
cd /opt/python/current/app

alias db='cd /opt/python/current/app; python /opt/python/current/app/manage.py shell_plus'

alias log_commands="tail -f  /var/log/cfn-init-cmd.log"
alias logo='nano +1000000000 /var/log/httpd/error_log' #open log, go to end
alias log='tail -f /var/log/httpd/error_log' #tail follow apache log
alias logc='tail -f /var/log/eb-*'
alias loge='logc'
alias logeb='logc'

alias sudo="sudo "
alias n="nano "
alias sn="sudo nano "

alias pyc='find . -type f -name "*.pyc" -delete -print'
alias htop="htop -d 5"

alias u="cd .."
alias uu="cd ../.."
alias uuu="cd ../../.."

alias ls='ls --color=auto'
alias la='ls -A'
alias ll='ls -lh'
alias lh='ls -lhX --color=auto'

alias py="python"
alias ipy="ipython"

alias ls='ls --color=auto -h'
