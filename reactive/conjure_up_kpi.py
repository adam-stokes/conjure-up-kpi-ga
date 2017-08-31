#!/usr/bin/env python3

"""
Copyright (c) 2016, 2017 Canonical, Ltd.
Authors: Paul Gear, Adam Stokes

Hooks for conjure-up-kpi charm.
"""

import base64
import glob
import os
import re

from charmhelpers.core import (
    host,
    hookenv,
    unitdata,
)

from charms.reactive import (
    main,
    remove_state,
    set_state,
)

from charms.reactive.decorators import (
    hook,
    when,
    when_all,
    when_not,
)

from charmhelpers.core.templating import render


def status(status, msg):
    hookenv.log('%s: %s' % (status, msg))
    hookenv.status_set(status, msg)


def active(msg):
    status('active', msg)


def blocked(msg):
    status('blocked', msg)


def maint(msg):
    status('maintenance', msg)


def write_config_file():
    """
    Create /etc/cu-kpi.ini.
    """
    cfg_file = 'cu-kpi.ini'
    kv = unitdata.kv()
    push_gateway = kv.get('push_gateway')
    maint('rendering config %s' % (cfg_file,))
    script_dir = '/srv/cu-kpi/parts'
    scripts = [x for x in os.listdir(
        script_dir) if re.match(r'^[-_A-Za-z]+$', x)]
    render(
        source=cfg_file,
        target='/etc/' + cfg_file,
        perms=0o755,
        context={
            'push_gateway': push_gateway,
            'scripts': scripts,
            'config': hookenv.config(''),
        },
    )
    return push_gateway


def write_cron_job():
    """
    Create cron job
    """
    dst = '/etc/cron.d/cu-kpi'
    cron_job = 'cron-job'
    maint('installing %s to %s' % (cron_job, dst))
    kv = unitdata.kv()
    render(
        source=cron_job,
        target=dst,
        perms=0o755,
        context={
            'script_dir': '/srv/cu-kpi/parts',
            'script_name': 'cu-kpi',
            'user': kv.get('run-as'),
        },
    )


def write_ga_dashboard_credentials():
    """
    Save GA credentials in the configured file.
    """
    kv = unitdata.kv()
    creds_file = kv.get('cu-ga-dashboard-credentials-file')
    maint('saving GA credentials to %s' % (creds_file,))
    dst_dir = os.path.dirname(creds_file)
    user = kv.get('run-as')
    host.mkdir(dst_dir, owner=user, perms=0o700)
    creds_blob = kv.get('cu-ga-dashboard-credentials')
    creds_data = base64.b64decode(creds_blob.encode())
    host.write_file(creds_file, creds_data, owner=user)


@when_all(
    'cu-kpi.configured',
    'push_gateway.configured',
)
def write_config():
    blocked('Unable to configure charm - please see log')
    write_ga_dashboard_credentials()
    push_gateway = write_config_file()
    write_cron_job()
    active('Configured push gateway %s' % (push_gateway,))


@when('juju-info.available')
def relation_joined(relation):
    """
    Get private address of push gateway from juju-info relation; save in unit data.
    cf. https://gist.github.com/marcoceppi/fb911c63eac6a1db5c649a2f96439074
    """
    remove_state('push_gateway.configured')
    push_gateway = relation.private_address()
    kv = unitdata.kv()
    kv.set('push_gateway', push_gateway)
    set_state('push_gateway.configured')
    active('Set push_gateway.configured state')


@when_not('push_gateway.configured')
def not_configured():
    blocked('Waiting for push-gateway relation')


@hook('config-changed')
def config_changed():
    remove_state('cu-kpi.configured')
    maint('checking configuration')

    kv = unitdata.kv()
    config_items = (
        'cu-ga-dashboard-credentials',
        'cu-ga-dashboard-credentials-file',
        'run-as',
    )
    for c in config_items:
        item = hookenv.config(c)
        if len(item) <= 0:
            blocked('%s must be set' % (c,))
            remove_state('cu-kpi.configured')
            return
        else:
            kv.set(c, item)
    set_state('cu-kpi.configured')


@hook(
    'install',
    'upgrade-charm',
)
def install_files():
    # this part lifted from haproxy charm hooks.py
    src = os.path.join(os.environ["CHARM_DIR"], "files/thirdparty/")
    dst = '/srv/cu-kpi/parts/'
    maint('Copying scripts from %s to %s' % (src, dst))
    host.mkdir(dst, perms=0o755)
    for fname in glob.glob(os.path.join(src, "*")):
        host.rsync(fname, os.path.join(dst, os.path.basename(fname)))

    # Template files may have changed in an upgrade, so we need to rewrite
    # them
    config_changed()


if __name__ == '__main__':
    main()
