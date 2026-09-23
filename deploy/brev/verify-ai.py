"""Check the real HTTP analysis; demo/fallback is a failure for --require-openai."""
import argparse
import json
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--require-openai', action='store_true')
    args = parser.parse_args()
    request = urllib.request.Request(
        args.base_url.rstrip('/') + '/analyze',
        data=json.dumps({'area': 'Astana District X', 'time_window_minutes': 60}).encode(),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(f'FAIL: HTTP analysis unavailable ({type(exc).__name__})')
    mode = result.get('agent_mode')
    steps = result.get('agent_steps', [])
    incident = result.get('incident') or {}
    print(json.dumps({'agent_mode': mode, 'incident_id': incident.get('id'),
                      'tools': [s.get('tool') for s in steps if s.get('status') == 'completed'],
                      'errors': [s.get('message') for s in steps if s.get('status') == 'error']},
                     ensure_ascii=False, indent=2))
    if args.require_openai and mode != 'openai':
        raise SystemExit('FAIL: real OpenAI was NOT verified; demo/fallback is not success.')
    if not incident.get('id'):
        raise SystemExit('FAIL: no incident selected for the demo district.')
    print('PASS: ' + ('real OpenAI tool analysis' if mode == 'openai' else 'demo analysis only'))


if __name__ == '__main__':
    main()
