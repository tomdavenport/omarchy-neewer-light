"""Validate commands before committing settings or scheduling hardware writes."""
import asyncio
import logging
from light_config import save, selected, ROLES
from light_effects import illuminate, SPEEDS


def command(service, action, value=None):
    if action in ('status', 'probe'):
        if action == 'probe':
            service.probe_requested = True
            service.wake.set()
        return service.snapshot()
    if action == 'scan':
        if not service.scanning:
            service.scanning = True
            task = asyncio.create_task(service.scan())
            service.tasks.add(task)
            task.add_done_callback(service.tasks.discard)
        service.publish('Looking for your RGB1…')
        return service.snapshot()
    cfg = dict(service.cfg)
    updates = {}
    if action == 'select':
        if not any(device['address'] == value for device in service.devices):
            raise ValueError('Choose a light from the search results.')
        cfg.update(address=value, setup_complete=False, last_requested_power='on')
        updates.update(test_success=False, dirty=False, last_signature=None, pending_power=None)
    elif action == 'confirm':
        if not service.test_success:
            raise ValueError('Test the colour before finishing setup.')
        cfg['setup_complete'] = True
        updates['dirty'] = cfg['follow']
    elif action in ('role', 'preview'):
        value = {'main': 'accent', 'secondary': 'complementary', 'neutral': 'accent'}.get(value, value)
        if value not in ROLES:
            raise ValueError('Choose Main, Complement or Alternate.')
        cfg['role'], cfg['mode'], updates['dirty'] = value, 'steady', True
        if action == 'preview':
            if not cfg['address']:
                raise ValueError('Set up your light first.')
            illuminate(cfg)
            updates.update(pending_power='on', force=True)
    elif action == 'mode':
        if value not in ('steady', 'cycle'):
            raise ValueError('Choose steady or cycle.')
        cfg['role'] = service.cycle.role or cfg['role']
        cfg['mode'], updates['dirty'] = value, True
        if value == 'cycle':
            if not cfg['setup_complete']:
                raise ValueError('Finish light setup before cycling colours.')
            illuminate(cfg)
            cfg['follow'] = True
            updates.update(pending_power='on', force=True)
    elif action == 'speed':
        if value not in SPEEDS:
            raise ValueError('Choose slow, medium or fast.')
        cfg['speed'] = value
        if cfg.get('mode') == 'cycle':
            cfg['role'] = service.cycle.role or cfg['role']
    elif action == 'brightness':
        number = int(value)
        if not 0 <= number <= 100:
            raise ValueError('Brightness must be between 0 and 100.')
        cfg['brightness'], updates['dirty'] = number, True
        if number:
            cfg['last_nonzero_brightness'] = number
    elif action == 'follow':
        if value not in ('on', 'off'):
            raise ValueError('Choose follow on or off.')
        cfg['follow'] = value == 'on'
        if not cfg['follow'] and cfg.get('mode') == 'cycle':
            cfg.update(mode='steady', role=service.cycle.role or cfg['role'])
        updates['dirty'] = cfg['follow'] and cfg['setup_complete']
    elif action in ('on', 'off', 'test'):
        if not cfg['address']:
            raise ValueError('Set up your light first.')
        cfg['last_requested_power'] = 'off' if action == 'off' else 'on'
        if action != 'off':
            illuminate(cfg)
        updates.update(pending_power=action, dirty=action != 'off')
        if action == 'test':
            updates['test_success'] = False
    elif action in ('theme', 'hook'):
        if action == 'hook' and not (cfg['follow'] and cfg['setup_complete']):
            return service.snapshot()
        if not cfg['address']:
            raise ValueError('Set up your light first.')
        updates.update(dirty=True, force=action == 'theme')
    else:
        raise ValueError('Unknown light command.')
    if action in ('role', 'preview', 'select'):
        cfg.pop('held_mix', None)
    if (service.cfg.get('mode') == 'cycle' and cfg.get('mode') == 'steady'
            and action in ('mode', 'follow') and service.cycle.weights is not None):
        cfg['held_mix'] = list(service.cycle.weights)
    theme, roles, colour = selected(cfg)
    save(cfg)
    service.cfg = cfg
    if action in ('role', 'preview', 'select', 'on', 'off', 'test') or (action == 'follow' and not cfg['follow']):
        service.transition.cancel(theme, roles)
    logging.info('RGB1 control %s %s', action, value if value is not None else '')
    if action in ('role', 'preview', 'mode', 'speed', 'follow', 'select', 'confirm', 'on'):
        service.cycle.reset(cfg, preserve=action in ('speed', 'on'))
    for key, val in updates.items():
        setattr(service, key, val)
    service.theme, service.roles, service.colour = theme, roles, colour
    service.generation += 1
    service.wake.set()
    service.publish('Updating light…' if service.dirty or service.pending_power else 'Settings saved.')
    return service.snapshot()
