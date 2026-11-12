"""A deliberately small, stateless CUA observation language, never a JS evaluator.

Only direct inventory queries are supported. Persistent bindings, target handles,
navigation and input cannot be authorized by inspecting arbitrary JavaScript.
"""
import json
import re


def observation(args):
    if not isinstance(args, dict):
        raise ValueError('CUA input must be an object')
    if set(args) == {'completion_summary'} and isinstance(args['completion_summary'], str):
        return
    if set(args) - {'code', 'title', 'timeout_ms'}:
        raise ValueError('unsupported CUA input fields')
    code = args.get('code')
    if not isinstance(code, str) or len(code) > 2048:
        raise ValueError('CUA inventory query must be a string of at most 2048 characters')
    match = re.fullmatch(
        r'\s*await cua\.(getState|listApps|listBrowsers|listTabs)\((.*?)\);?\s*',
        code if isinstance(code, str) else '', re.DOTALL)
    if not match:
        raise ValueError('CUA supports direct inventory observation only: await cua.getState(); '
                         'interaction/navigation/mutation and arbitrary scripts require a separate supported capability')
    raw = match[2].strip()
    try:
        options = json.loads(raw) if raw else {}
    except RecursionError as error:
        raise ValueError('nested CUA observation options are unsupported') from error
    allowed = {'emit', 'browser'} if match[1] == 'listTabs' else {'emit'}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError('CUA observation options must be a literal JSON object with supported fields')
    if 'emit' in options and not isinstance(options['emit'], bool):
        raise ValueError('CUA emit must be boolean')
    if 'browser' in options and (not isinstance(options['browser'], str) or not options['browser']):
        raise ValueError('CUA browser must be a literal nonempty ID')
