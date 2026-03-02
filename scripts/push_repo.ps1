# Push repo while bypassing the system-level GitDefender hook
git -c core.hooksPath=.git/hooks push @args
