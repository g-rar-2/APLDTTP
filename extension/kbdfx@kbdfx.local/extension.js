// Animación del teclado (kbdfx) - botón en los ajustes rápidos de GNOME Shell.
// Lanza el programa `kbdfx` con el modo elegido y lo detiene con SIGTERM,
// así kbdfx deja la luz como estaba.

import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const ICONO = 'keyboard-brightness-symbolic';
const TITULO = 'Animación del teclado';
const SIGTERM = 15;

const MODOS = [
    ['respirar', 'Respirar'],
    ['pulsar', 'Pulsar'],
    ['latido', 'Latido'],
    ['onda', 'Onda'],
    ['eco', 'Eco al teclear'],
    ['teclear', 'Encender al teclear'],
    ['musica', 'Música'],
    ['morse', 'Morse'],
    ['bateria', 'Aviso de batería'],
    ['atenuado', 'Atenuado (experimental)'],
    ['demo', 'Demo'],
];

const VELOCIDADES = [
    ['0.5', 'Lenta'],
    ['1', 'Normal'],
    ['2', 'Rápida'],
];

const POR_DEFECTO = {
    activo: false,
    modo: 'respirar',
    velocidad: '1',
    logo: false,
    texto_morse: 'sos',
};

// ---------------------------------------------------------------- estado
// Se guarda en ~/.config/kbdfx/extension.json para recordar el modo
// y si estaba encendido al volver a iniciar sesión.

function rutaEstado() {
    return GLib.build_filenamev([GLib.get_user_config_dir(), 'kbdfx', 'extension.json']);
}

function leerEstado() {
    try {
        const [ok, bytes] = GLib.file_get_contents(rutaEstado());
        if (ok)
            return {...POR_DEFECTO, ...JSON.parse(new TextDecoder().decode(bytes))};
    } catch (e) {
        // sin archivo todavía: valores por defecto
    }
    return {...POR_DEFECTO};
}

function guardarEstado(estado) {
    try {
        GLib.mkdir_with_parents(GLib.path_get_dirname(rutaEstado()), 0o755);
        GLib.file_set_contents(rutaEstado(), JSON.stringify(estado, null, 2));
    } catch (e) {
        console.warn(`kbdfx: no se pudo guardar el estado: ${e}`);
    }
}

function nombreModo(id) {
    return MODOS.find(([m]) => m === id)?.[1] ?? id;
}

function logoEscribible() {
    try {
        const info = Gio.File.new_for_path('/sys/class/leds/tpacpi::lid_logo_dot/brightness')
            .query_info('access::can-write', Gio.FileQueryInfoFlags.NONE, null);
        return info.get_attribute_boolean('access::can-write');
    } catch (e) {
        return false;
    }
}

const MARCA = PopupMenu.Ornament.CHECK ?? PopupMenu.Ornament.DOT;

// ---------------------------------------------------------------- botón

const KbdfxToggle = GObject.registerClass(
class KbdfxToggle extends QuickMenuToggle {
    constructor() {
        super({
            title: 'Animación',
            iconName: ICONO,
            toggleMode: true,
        });

        this._estado = leerEstado();
        this._proc = null;

        this.menu.setHeader(ICONO, TITULO);

        // Logo de la tapa (arriba, siempre visible)
        this._itemLogo = new PopupMenu.PopupSwitchMenuItem(
            'Animar el logo de la tapa', this._estado.logo);
        this._itemLogo.connect('toggled', (_item, activo) => {
            this._estado.logo = activo;
            if (activo && !logoEscribible()) {
                Main.notify(TITULO, 'No hay permiso para controlar el logo de la tapa. ' +
                    'Ejecuta install.sh otra vez o reinicia la laptop.');
            }
            this._aplicarCambio();
        });
        this.menu.addMenuItem(this._itemLogo);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Modos: submenú plegable con desplazamiento
        this._subModo = new PopupMenu.PopupSubMenuMenuItem('Modo', false);
        this._subModo.menu.actor.style = 'max-height: 14em;';
        this._itemsModo = new Map();
        for (const [id, nombre] of MODOS) {
            const item = this._subModo.menu.addAction(nombre, () => this._elegirModo(id));
            this._itemsModo.set(id, item);
        }
        this.menu.addMenuItem(this._subModo);

        // Velocidad: submenú plegable
        this._subVel = new PopupMenu.PopupSubMenuMenuItem('Velocidad', false);
        this._itemsVelocidad = new Map();
        for (const [valor, nombre] of VELOCIDADES) {
            const item = this._subVel.menu.addAction(nombre, () => {
                this._estado.velocidad = valor;
                this._aplicarCambio();
            });
            this._itemsVelocidad.set(valor, item);
        }
        this.menu.addMenuItem(this._subVel);

        this.checked = this._estado.activo;
        this._idChecked = this.connect('notify::checked', () => {
            this._estado.activo = this.checked;
            guardarEstado(this._estado);
            if (this.checked)
                this._iniciar();
            else
                this._detener();
            this._actualizarVista();
        });

        this._actualizarVista();
        if (this.checked)
            this._iniciar();
    }

    _elegirModo(id) {
        this._estado.modo = id;
        if (this.checked) {
            this._aplicarCambio();
        } else {
            // Elegir un modo lo enciende directamente
            this.checked = true;
        }
    }

    _aplicarCambio() {
        guardarEstado(this._estado);
        if (this.checked)
            this._iniciar();
        this._actualizarVista();
    }

    _actualizarVista() {
        this.subtitle = this.checked ? nombreModo(this._estado.modo) : null;
        this.menu.setHeader(ICONO, TITULO,
            this.checked ? nombreModo(this._estado.modo) : 'Apagada');

        this._subModo.label.text = `Modo: ${nombreModo(this._estado.modo)}`;
        const vel = VELOCIDADES.find(([v]) => v === String(this._estado.velocidad));
        this._subVel.label.text = `Velocidad: ${vel ? vel[1] : this._estado.velocidad}`;

        for (const [id, item] of this._itemsModo)
            item.setOrnament(id === this._estado.modo ? MARCA : PopupMenu.Ornament.NONE);
        for (const [valor, item] of this._itemsVelocidad)
            item.setOrnament(valor === String(this._estado.velocidad) ? MARCA : PopupMenu.Ornament.NONE);
    }

    _argumentos() {
        const exe = GLib.find_program_in_path('kbdfx') ?? '/usr/local/bin/kbdfx';
        const e = this._estado;
        const argv = [exe, e.modo];
        if (e.modo === 'morse')
            argv.push(e.texto_morse || 'sos');
        argv.push('--velocidad', String(e.velocidad));
        if (e.logo)
            argv.push('--logo');
        return argv;
    }

    _iniciar() {
        this._detener();

        // Si hay un arranque automático por systemd, lo pausamos para que no compitan
        try {
            Gio.Subprocess.new(['systemctl', '--user', 'stop', 'kbdfx.service'],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (e) {
            // sin systemd de usuario: no pasa nada
        }

        let proc;
        try {
            proc = Gio.Subprocess.new(this._argumentos(),
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE);
        } catch (e) {
            Main.notify(TITULO, 'No se encontró kbdfx. Ejecuta install.sh otra vez.');
            this._apagarDespues();
            return;
        }
        this._proc = proc;

        proc.communicate_utf8_async(null, null, (p, res) => {
            let error = '';
            try {
                [, , error] = p.communicate_utf8_finish(res);
            } catch (e) {
                error = String(e);
            }
            if (this._proc !== p)
                return; // lo detuvimos nosotros o se reemplazó por otro modo
            this._proc = null;
            Main.notify(TITULO, (error ?? '').trim() || 'kbdfx se detuvo.');
            this._apagarDespues();
        });
    }

    _apagarDespues() {
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this.checked = false;
            return GLib.SOURCE_REMOVE;
        });
    }

    _detener() {
        if (!this._proc)
            return;
        const p = this._proc;
        this._proc = null;
        try {
            p.send_signal(SIGTERM); // kbdfx restaura la luz al recibirla
        } catch (e) {
            // ya había terminado
        }
    }

    destroy() {
        // Se llama al bloquear la pantalla o desactivar la extensión:
        // detenemos la animación sin cambiar el estado guardado.
        if (this._idChecked) {
            this.disconnect(this._idChecked);
            this._idChecked = 0;
        }
        this._detener();
        super.destroy();
    }
});

// ---------------------------------------------------------------- indicador

const KbdfxIndicator = GObject.registerClass(
class KbdfxIndicator extends SystemIndicator {
    constructor() {
        super();

        // Icono en la barra superior, visible solo mientras hay animación
        this._indicator = this._addIndicator();
        this._indicator.icon_name = ICONO;

        const toggle = new KbdfxToggle();
        toggle.bind_property('checked', this._indicator, 'visible',
            GObject.BindingFlags.SYNC_CREATE);
        this.quickSettingsItems.push(toggle);
    }

    destroy() {
        this.quickSettingsItems.forEach(item => item.destroy());
        super.destroy();
    }
});

export default class KbdfxExtension extends Extension {
    enable() {
        this._indicator = new KbdfxIndicator();
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
