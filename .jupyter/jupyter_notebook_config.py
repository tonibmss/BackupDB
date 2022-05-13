## Supply overrides for terminado. Currently only supports "shell_command".
c.NotebookApp.terminado_settings = {
    'shell_command': ['/usr/bin/env', 'TERM=xterm-256color', '/bin/bash'],
}
