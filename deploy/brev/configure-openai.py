"""Run interactively on the server; never put the API key in shell arguments."""
import getpass
import os
from pathlib import Path
import sys

from dotenv import dotenv_values, set_key


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Run in an interactive SSH terminal.')
    path = Path(__file__).resolve().parents[2] / 'backend' / '.env'
    if path.is_symlink():
        raise SystemExit('Refusing to modify a symlink.')
    current = dotenv_values(path) if path.exists() else {}
    key = getpass.getpass('OpenAI API key (hidden; Enter keeps existing): ').strip()
    key = key or current.get('OPENAI_API_KEY', '')
    if not key or not key.startswith('sk-') or any(c.isspace() for c in key):
        raise SystemExit('Enter an OpenAI API key, not a project/link identifier. Nothing saved.')
    default = current.get('OPENAI_MODEL') or 'gpt-4.1-mini'
    model = input(f'Model ID [{default}]: ').strip() or default
    if any(c.isspace() for c in model):
        raise SystemExit('Model ID cannot contain whitespace. Nothing saved.')
    os.umask(0o077)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    set_key(str(path), 'OPENAI_API_KEY', key)
    set_key(str(path), 'OPENAI_MODEL', model)
    path.chmod(0o600)
    print('Saved backend/.env with permissions 600. Key is not printed.')
    print('Next: sudo systemctl restart network-intelligence-api')


if __name__ == '__main__':
    main()
