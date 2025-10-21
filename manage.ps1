param(
    [Parameter(Position=0)]
    [ValidateSet('setup-venv', 'start', 'compile-ui')]
    $action
)

switch ($action) {
    # User commands
    'setup-venv' {
        if (test-path .venv/scripts/activate.ps1) {
            write-host 'Using existing env.'
            .venv/scripts/activate.ps1
        } else {
            write-host 'Creating env using system python...'
            python -m venv .venv
            .venv/scripts/activate.ps1
            write-host 'Installing dependencies...'
            pip install vosk pyside6 sounddevice librosa
        }
    }
    'start' {
        write-host 'Starting main.py...'
        # Workaround to handle Ctrl+C properly
        $process = start-process python main.py -nonewwindow -passthru
        try { wait-process -id $process.Id }
        finally { stop-process -id $process.Id -erroraction ignore }
    }

    # Developer commands
    'compile-ui' {
        write-host 'Compiling mainwindow.ui...'
        pyside6-uic .\mainwindow.ui -o ui_mainwindow.py
    }
}
