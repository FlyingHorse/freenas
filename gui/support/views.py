#+
# Copyright 2013 iXsystems, Inc.
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
import json
import logging
import os

from django.core.files.base import File
from django.http import HttpResponse
from django.shortcuts import render

from freenasUI.common.system import get_sw_name, get_sw_version
from freenasUI.freeadmin.apppool import appPool
from freenasUI.support import utils
from freenasUI.system.utils import debug_get_settings, debug_run

log = logging.getLogger("support.views")
TICKET_PROGRESS = '/tmp/.ticketprogress'


def index(request):
    sw_name = get_sw_name().lower()

    context = {}
    for c in appPool.hook_view_context('support.index', request):
        context.update(c)

    return render(request, 'support/home_%s.html' % sw_name, context)


def ticket(request):
    if request.method == 'POST':

        step = 2 if request.FILES.getlist('attachment') else 1

        files = []
        if request.POST.get('debug') == 'on':
            with open(TICKET_PROGRESS, 'w') as f:
                f.write(json.dumps({'indeterminate': True, 'step': step}))
            step += 1

            mntpt, direc, dump = debug_get_settings()
            debug_run(direc)
            files.append(File(open(dump, 'rb'), name=os.path.basename(dump)))

        with open(TICKET_PROGRESS, 'w') as f:
            f.write(json.dumps({'indeterminate': True, 'step': step}))
        step += 1

        data = {
            'title': request.POST.get('subject'),
            'body': request.POST.get('desc'),
            'version': get_sw_version().split('-', 1)[-1],
            'category': request.POST.get('category'),
        }

        if get_sw_name().lower() == 'freenas':
            data.update({
                'user': request.POST.get('username'),
                'password': request.POST.get('password'),
                'type': request.POST.get('type'),
            })
        else:
            data.update({
                'phone': request.POST.get('phone', '555'),
                'name': request.POST.get('name', 'John'),
                'company': request.POST.get('company', 'iXsystems'),
                'email': request.POST.get('email', 'william88@gmail.com'),
            })

        success, msg, tid = utils.new_ticket(data)

        with open(TICKET_PROGRESS, 'w') as f:
            f.write(json.dumps({'indeterminate': True, 'step': step}))
        step += 1

        data = {'message': msg, 'error': not success}

        if not success:
            pass
        else:

            files.extend(request.FILES.getlist('attachment'))
            for f in files:
                success, attachmsg = utils.ticket_attach({
                    'user': request.POST.get('username'),
                    'password': request.POST.get('password'),
                    'ticketnum': tid,
                }, f)

        data = (
            '<html><body><textarea>%s</textarea></boby></html>' % (
                json.dumps(data),
            )
        )
        return HttpResponse(data)
    return render(request, 'support/ticket.html', {
        'sw_name': get_sw_name().lower(),
    })


def ticket_progress(request):
    with open(TICKET_PROGRESS, 'r') as f:
        try:
            data = json.loads(f.read())
        except:
            data = {'indeterminate': True}
    return HttpResponse(json.dumps(data), content_type='application/json')
