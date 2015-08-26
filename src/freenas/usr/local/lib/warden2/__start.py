#!/usr/bin/env python2.7
#
# Copyright 2015 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################
from __is_running import __is_jail_running
from __pipeopen import __pipeopen


def __start_jail(args):
    """
    Takes 1 argument and supplies that to `__is_jail_running`
    Then if it is not, passes the name to `iocage start`
    Otherwise tells the user it is already running
    """
    (retcode, results_stdout, results_stderr) = __pipeopen(
        ['/usr/local/sbin/iocage',
         'get',
         'hostname',
         '{0}'.format(args.jail)])
    _uuid = results_stdout.rstrip('\n')
    if not __is_jail_running(_uuid):
        (retcode, results_stdout, results_stderr) = __pipeopen(
            ['/usr/local/sbin/iocage',
             'start',
             '{0}'.format(args.jail)])
        print '  Starting jail: {0}'.format(args.jail)
        if retcode == 0:
            print '  Jail started successfully!'
        else:
            if not results_stderr:
                print '\n', results_stdout
            else:
                print '  Jail did not start successfully.'
                print '  Error was:', results_stderr
    else:
        print '  Jail is already running!'