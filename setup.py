#!/usr/bin/env python3
import os, sys, subprocess, platform

TEXTS = {
    'pt_BR': {
        'select': 'Escolha o idioma:',
        'Portuguese': 'Portugues (Brasil)',
        'English': 'English (USA)',
        'success': 'Instalacao concluida!',
    },
    'en_US': {
        'select': 'Choose language:',
        'Portuguese': 'Portuguese (Brasil)',
        'English': 'English (USA)',
        'success': 'Installation complete!',
    }
}

def main():
    print('
' + '='*60)
    print('Seeker.Bot Setup Wizard')
    print('='*60)
    print('[1] Portugues (Brasil)')
    print('[2] English (USA)')
    choice = input('Choose (1-2): ').strip()
    lang = 'pt_BR' if choice == '1' else 'en_US'
    
    print('
Setup em progresso...')
    print('='*60)
    print(TEXTS[lang]['success'])
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
