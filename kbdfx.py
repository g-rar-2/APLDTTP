#!/usr/bin/env python3
"""kbdfx - animaciones para la retroiluminacion del teclado ThinkPad (thinkpad_acpi).

Uso rapido:
    kbdfx                (sin nada: abre el menu)
    kbdfx respirar
    kbdfx pulsar --velocidad 2 --logo
    kbdfx teclear --tiempo 5
    kbdfx eco
    kbdfx musica
    kbdfx morse "hola mundo"
    kbdfx fijo 1
Ctrl+C detiene la animacion y deja la luz como estaba.
"""
import argparse
import array
import glob
import math
import os
import shutil
import signal
import subprocess
import sys
import time

LEDS_DIR = os.environ.get("KBDFX_LEDS", "/sys/class/leds")
KBD = os.path.join(LEDS_DIR, "tpacpi::kbd_backlight")
LOGO = os.path.join(LEDS_DIR, "tpacpi::lid_logo_dot")


class Led:
    def __init__(self, ruta):
        self.ruta = os.path.join(ruta, "brightness")
        with open(os.path.join(ruta, "max_brightness")) as f:
            self.max = int(f.read())
        with open(self.ruta) as f:
            self.original = int(f.read())
        self.ultimo = None

    def set(self, v):
        v = max(0, min(self.max, int(v)))
        if v == self.ultimo:
            return
        with open(self.ruta, "w") as f:
            f.write(str(v))
        self.ultimo = v

    def restaurar(self):
        self.ultimo = None
        self.set(self.original)


class Salida:
    """Envia un nivel 0-2 al teclado y, opcionalmente, al punto rojo del logo."""

    def __init__(self, con_logo):
        try:
            self.kbd = Led(KBD)
        except PermissionError:
            sys.exit("Sin permiso para escribir la luz. Ejecuta install.sh o usa sudo.")
        except FileNotFoundError:
            sys.exit(f"No se encontro {KBD}. Esta cargado el modulo thinkpad_acpi?")
        self.logo = None
        if con_logo and os.path.isdir(LOGO):
            try:
                self.logo = Led(LOGO)
            except OSError:
                print("Aviso: no se puede controlar el logo, sigo sin el.", file=sys.stderr)

    def __call__(self, nivel):
        self.kbd.set(nivel)
        if self.logo:
            self.logo.set(self.logo.max if nivel > 0 else 0)

    def restaurar(self):
        self.kbd.restaurar()
        if self.logo:
            self.logo.restaurar()


# ---------------------------------------------------------------- animaciones

def secuencia(out, pasos, vel):
    """Repite para siempre una lista de (nivel, segundos)."""
    while True:
        for nivel, seg in pasos:
            out(nivel)
            time.sleep(seg / vel)


def modo_pulsar(out, a):
    secuencia(out, [(2, 0.4), (0, 0.4)], a.velocidad)


def modo_respirar(out, a):
    secuencia(out, [(0, 0.5), (1, 0.35), (2, 0.7), (1, 0.35)], a.velocidad)


def modo_latido(out, a):
    secuencia(out, [(2, 0.12), (0, 0.12), (2, 0.12), (0, 0.8)], a.velocidad)


def modo_onda(out, a):
    secuencia(out, [(1, 0.25), (2, 0.25), (1, 0.25), (2, 0.25), (1, 0.25), (0, 0.6)], a.velocidad)


MORSE = {
    "a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.", "g": "--.",
    "h": "....", "i": "..", "j": ".---", "k": "-.-", "l": ".-..", "m": "--", "n": "-.",
    "ñ": "--.--", "o": "---", "p": ".--.", "q": "--.-", "r": ".-.", "s": "...", "t": "-",
    "u": "..-", "v": "...-", "w": ".--", "x": "-..-", "y": "-.--", "z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}


def modo_morse(out, a):
    p = 0.15 / a.velocidad
    while True:
        for palabra in a.texto.lower().split():
            for letra in palabra:
                for s in MORSE.get(letra, ""):
                    out(2)
                    time.sleep(p if s == "." else 3 * p)
                    out(0)
                    time.sleep(p)
                time.sleep(2 * p)
            time.sleep(4 * p)
        time.sleep(10 * p)


def contador_teclado():
    """Suma de interrupciones del teclado interno (IRQ 1, i8042).
    Solo cuenta pulsaciones: no lee que teclas se presionan."""
    with open("/proc/interrupts") as f:
        for linea in f:
            if linea.split(":")[0].strip() == "1" and "i8042" in linea:
                return sum(int(x) for x in linea.split()[1:] if x.isdigit())
    return None


def modo_teclear(out, a):
    if contador_teclado() is None:
        sys.exit("No encontre la interrupcion del teclado (i8042) en /proc/interrupts.")
    previo = contador_teclado()
    ultimo = 0.0
    out(0)
    while True:
        actual = contador_teclado()
        ahora = time.monotonic()
        if actual != previo:
            previo, ultimo = actual, ahora
            out(2)
        else:
            quieto = ahora - ultimo
            if quieto > a.tiempo + 0.6:
                out(0)
            elif quieto > a.tiempo:
                out(1)  # se apaga en dos pasos
        time.sleep(0.05)


def modo_eco(out, a):
    """Cada tecla da un destello que se desvanece por pasos (alto, bajo, apagado).
    Escribir rapido acumula 'energia', asi que la luz tarda mas en apagarse."""
    if contador_teclado() is None:
        sys.exit("No encontre la interrupcion del teclado (i8042) en /proc/interrupts.")
    previo = contador_teclado()
    energia = 0.0
    caida = 2.0 * a.velocidad  # unidades de energia por segundo
    tope = 1.0 + a.cola
    t_prev = time.monotonic()
    out(0)
    while True:
        time.sleep(0.02)
        ahora = time.monotonic()
        energia = max(0.0, energia - caida * (ahora - t_prev))
        t_prev = ahora
        actual = contador_teclado()
        if actual != previo:
            teclas = max(1, (actual - previo) // 2)  # cada tecla = pulsar + soltar
            previo = actual
            energia = min(tope, max(energia, 1.5) + 0.3 * teclas)
        out(2 if energia > 1.0 else 1 if energia > 0.0 else 0)


def modo_musica(out, a):
    if not shutil.which("parec"):
        sys.exit("Falta 'parec'. Instalalo con: sudo apt install pulseaudio-utils")
    cmd = ["parec", "--raw", "--format=s16le", "--rate=8000", "--channels=1",
           "--latency-msec=40", "-d", "@DEFAULT_MONITOR@"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pico = 800.0
    try:
        while True:
            datos = proc.stdout.read(800)  # ~50 ms
            if not datos:
                sys.exit("No se pudo leer el audio (parec termino).")
            datos = datos[: len(datos) // 2 * 2]
            muestras = array.array("h", datos)
            if not muestras:
                continue
            rms = math.sqrt(sum(x * x for x in muestras) / len(muestras))
            pico = max(rms, pico * 0.997, 300.0)  # ganancia automatica
            r = rms / pico
            out(2 if r > 0.55 * a.sensibilidad else 1 if r > 0.2 * a.sensibilidad else 0)
    finally:
        proc.terminate()


def leer_bateria():
    for d in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            with open(os.path.join(d, "capacity")) as f:
                cap = int(f.read())
            with open(os.path.join(d, "status")) as f:
                estado = f.read().strip()
            return cap, estado
        except OSError:
            continue
    return None, None


def modo_bateria(out, a):
    if leer_bateria()[0] is None:
        sys.exit("No encontre la bateria en /sys/class/power_supply.")
    original = out.kbd.original
    while True:
        cap, estado = leer_bateria()
        if cap is not None and cap <= a.umbral and estado == "Discharging":
            fin = time.monotonic() + 30
            while time.monotonic() < fin:
                out(2); time.sleep(0.2)
                out(0); time.sleep(0.2)
        else:
            out(original)
            time.sleep(30)


def modo_atenuado(out, a):
    """Respiracion 'suave': alterna niveles muy rapido (PWM por software)
    para simular brillos intermedios. Experimental: puede parpadear."""
    periodo_pwm = 1.0 / a.hz
    t0 = time.monotonic()
    while True:
        t = time.monotonic() - t0
        objetivo = 1 - math.cos(2 * math.pi * t * a.velocidad / 4.0)  # 0..2
        bajo = int(objetivo)
        frac = objetivo - bajo
        if bajo >= 2 or frac < 0.05:
            out(bajo); time.sleep(periodo_pwm)
        else:
            out(bajo + 1); time.sleep(periodo_pwm * frac)
            out(bajo); time.sleep(periodo_pwm * (1 - frac))


MODOS_DEMO = [modo_pulsar, modo_respirar, modo_latido, modo_onda]


def _fin_de_modo(*_):
    raise TimeoutError


def modo_demo(out, a):
    signal.signal(signal.SIGALRM, _fin_de_modo)
    while True:
        for m in MODOS_DEMO:
            print(f"-> {m.__name__[5:]}")
            try:
                signal.setitimer(signal.ITIMER_REAL, 6)
                m(out, a)
            except TimeoutError:
                pass
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)


# ---------------------------------------------------------------------- menu

def nivel(v):
    if int(v) not in (0, 1, 2):
        raise ValueError
    return int(v)


# (modo, descripcion, [(opcion, pregunta, valor por defecto, tipo)])
MENU = [
    ("pulsar",   "Parpadeo de apagado a alto", []),
    ("respirar", "Sube y baja: 0, 1, 2, 1", []),
    ("latido",   "Dos pulsos y una pausa, como un corazon", []),
    ("onda",     "Oscila entre bajo y alto", []),
    ("demo",     "Recorre los modos basicos", []),
    ("morse",    "Escribe un texto en codigo Morse", [(None, "Texto", "sos", str)]),
    ("teclear",  "Se enciende al escribir y luego se apaga", [("--tiempo", "Segundos sin teclear antes de apagarse", "5", float)]),
    ("eco",      "Cada tecla da un destello que se desvanece", [("--cola", "Cola al escribir rapido (mayor = tarda mas)", "2", float)]),
    ("musica",   "El brillo sigue el volumen del audio", [("--sensibilidad", "Sensibilidad (menor = reacciona mas)", "1", float)]),
    ("bateria",  "Parpadea con bateria baja", [("--umbral", "Porcentaje de aviso", "15", int)]),
    ("atenuado", "Respiracion suave (experimental)", [("--hz", "Frecuencia del parpadeo rapido", "80", float)]),
    ("fijo",     "Deja un nivel fijo (0, 1 o 2)", [(None, "Nivel (0, 1 o 2)", "2", nivel)]),
]

SERVICIO = os.path.expanduser("~/.config/systemd/user/kbdfx.service")
ROJO, NEGRITA, GRIS, FIN = "\033[31m", "\033[1m", "\033[90m", "\033[0m"


def preguntar(texto, defecto, tipo):
    while True:
        r = input(f"  {texto} {GRIS}[{defecto}]{FIN}: ").strip() or defecto
        try:
            v = tipo(r)
            if tipo is float and v <= 0:
                raise ValueError
            return r
        except ValueError:
            print(f"  {ROJO}Valor no valido, intenta otra vez.{FIN}")


def si_no(texto, defecto=False):
    op = "S/n" if defecto else "s/N"
    r = input(f"  {texto} {GRIS}[{op}]{FIN}: ").strip().lower()
    return defecto if not r else r.startswith("s")


def systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    except FileNotFoundError:
        return None


def arranque_actual():
    """Devuelve el comando del arranque automatico activo, o None."""
    r = systemctl("is-enabled", "kbdfx.service")
    if r and r.stdout.strip() == "enabled" and os.path.exists(SERVICIO):
        with open(SERVICIO) as f:
            for linea in f:
                if linea.startswith("ExecStart="):
                    return linea.split("kbdfx", 1)[-1].strip().replace("%%", "%")
    wants = os.path.expanduser("~/.config/systemd/user/default.target.wants")
    for n in sorted(glob.glob(os.path.join(wants, "kbdfx@*.service"))):
        return os.path.basename(n)[6:-8]
    return None


def quitar_arranque():
    systemctl("disable", "--now", "kbdfx.service")
    wants = os.path.expanduser("~/.config/systemd/user/default.target.wants")
    for n in glob.glob(os.path.join(wants, "kbdfx@*.service")):
        systemctl("disable", "--now", os.path.basename(n))


def guardar_arranque(argv):
    import shlex
    quitar_arranque()
    exe = shutil.which("kbdfx") or os.path.abspath(sys.argv[0])
    comando = " ".join(shlex.quote(x) for x in [exe, *argv]).replace("%", "%%")
    os.makedirs(os.path.dirname(SERVICIO), exist_ok=True)
    with open(SERVICIO, "w") as f:
        f.write("[Unit]\nDescription=Animacion del teclado ThinkPad (kbdfx)\n\n"
                f"[Service]\nExecStart={comando}\nRestart=on-failure\n\n"
                "[Install]\nWantedBy=default.target\n")
    systemctl("daemon-reload")
    r = systemctl("enable", "--now", "kbdfx.service")
    return r is not None and r.returncode == 0


def ejecutar(argv, parser):
    try:
        a = parser.parse_args(argv)
        out = Salida(a.logo)
    except SystemExit as e:
        print(f"  {ROJO}{e.code}{FIN}")
        return
    if a.modo == "fijo":
        out(a.nivel)
        print(f"  Luz fija en nivel {a.nivel}.")
        return
    print(f"\n  {NEGRITA}Corriendo: kbdfx {' '.join(argv)}{FIN}")
    print(f"  {GRIS}Presiona Ctrl + C para volver al menu.{FIN}\n")
    try:
        globals()["modo_" + a.modo](out, a)
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        if e.code:
            print(f"  {ROJO}{e.code}{FIN}")
    finally:
        out.restaurar()


def menu(parser):
    detenido = False
    if os.environ.get("KBDFX_NO_SYSTEMD") != "1" and arranque_actual():
        # Pausa el arranque automatico para que no pelee con las pruebas
        r = systemctl("is-active", "kbdfx.service")
        if r and r.stdout.strip() == "active":
            systemctl("stop", "kbdfx.service")
            detenido = True
    try:
        while True:
            actual = arranque_actual() if os.environ.get("KBDFX_NO_SYSTEMD") != "1" else None
            print(f"\n{ROJO}{NEGRITA}  kbdfx{FIN}{NEGRITA} - luces del teclado ThinkPad{FIN}")
            print(f"  {GRIS}Arranque automatico: {actual or 'ninguno'}{FIN}\n")
            for n, (modo, desc, _) in enumerate(MENU, 1):
                print(f"  {NEGRITA}{n:>2}{FIN}  {modo:<9} {GRIS}{desc}{FIN}")
            print(f"\n  {NEGRITA} a{FIN}  Guardar un modo como arranque automatico")
            print(f"  {NEGRITA} x{FIN}  Quitar el arranque automatico")
            print(f"  {NEGRITA} q{FIN}  Salir\n")
            op = input("  Elige una opcion: ").strip().lower()

            if op in ("q", "s", "salir"):
                return
            if op == "x":
                quitar_arranque()
                detenido = False
                print("  Arranque automatico quitado.")
                continue
            guardar = op == "a"
            if guardar:
                op = input("  Numero del modo para el arranque automatico: ").strip()
            if not op.isdigit() or not 1 <= int(op) <= len(MENU):
                print(f"  {ROJO}Opcion no valida.{FIN}")
                continue

            modo, desc, opciones = MENU[int(op) - 1]
            print(f"\n  {NEGRITA}{modo}{FIN}: {desc}")
            print(f"  {GRIS}Pulsa Enter para dejar el valor entre corchetes.{FIN}")
            argv = [modo]
            for flag, texto, defecto, tipo in opciones:
                v = preguntar(texto, defecto, tipo)
                argv += [v] if flag is None else [flag, v]
            if modo != "fijo":
                v = preguntar("Velocidad (1 = normal, 2 = el doble)", "1", float)
                if v != "1":
                    argv += ["--velocidad", v]
            if si_no("Animar tambien el punto rojo del logo?"):
                argv.append("--logo")

            if guardar:
                if guardar_arranque(argv):
                    detenido = False
                    print(f"  Listo: 'kbdfx {' '.join(argv)}' arrancara solo al iniciar sesion.")
                else:
                    print(f"  {ROJO}No se pudo activar el servicio (systemctl --user).{FIN}")
            else:
                ejecutar(argv, parser)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        if detenido:
            systemctl("start", "kbdfx.service")


# ---------------------------------------------------------------------- main

def crear_parser():
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("-v", "--velocidad", type=float, default=1.0,
                       help="multiplicador de velocidad (1 = normal, 2 = el doble)")
    comun.add_argument("-l", "--logo", action="store_true",
                       help="animar tambien el punto rojo del logo de la tapa")

    p = argparse.ArgumentParser(prog="kbdfx", description="Animaciones para el teclado ThinkPad.")
    sub = p.add_subparsers(dest="modo", required=True)
    sub.add_parser("pulsar", parents=[comun], help="parpadeo encendido/apagado")
    sub.add_parser("respirar", parents=[comun], help="sube y baja 0-1-2-1")
    sub.add_parser("latido", parents=[comun], help="dos pulsos y pausa")
    sub.add_parser("onda", parents=[comun], help="oscila entre bajo y alto")
    sub.add_parser("demo", parents=[comun], help="recorre los modos basicos")
    s = sub.add_parser("morse", parents=[comun], help="escribe un texto en codigo Morse")
    s.add_argument("texto")
    s = sub.add_parser("teclear", parents=[comun], help="se enciende al escribir")
    s.add_argument("-t", "--tiempo", type=float, default=5.0,
                   help="segundos sin teclear antes de apagarse")
    s = sub.add_parser("eco", parents=[comun], help="destello que se desvanece con cada tecla")
    s.add_argument("-c", "--cola", type=float, default=2.0,
                   help="cuanto se acumula al escribir rapido (mayor = tarda mas en apagarse)")
    s = sub.add_parser("musica", parents=[comun], help="sigue el volumen del audio")
    s.add_argument("-s", "--sensibilidad", type=float, default=1.0,
                   help="menor = reacciona mas (p. ej. 0.7)")
    s = sub.add_parser("bateria", parents=[comun], help="parpadea con bateria baja")
    s.add_argument("-u", "--umbral", type=int, default=15, help="porcentaje de aviso")
    s = sub.add_parser("atenuado", parents=[comun], help="respiracion suave (experimental)")
    s.add_argument("--hz", type=float, default=80.0, help="frecuencia del PWM")
    s = sub.add_parser("fijo", parents=[comun], help="deja un nivel fijo y sale")
    s.add_argument("nivel", type=int, choices=[0, 1, 2])
    sub.add_parser("menu", help="menu interactivo para elegir el modo")
    return p


def main():
    p = crear_parser()

    def salir(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, salir)

    if len(sys.argv) == 1 or sys.argv[1:] == ["menu"]:
        menu(p)
        return

    a = p.parse_args()
    if a.velocidad <= 0:
        p.error("--velocidad debe ser mayor que 0")

    out = Salida(a.logo)
    if a.modo == "fijo":
        out(a.nivel)
        return

    try:
        globals()["modo_" + a.modo](out, a)
    except KeyboardInterrupt:
        pass
    finally:
        out.restaurar()


if __name__ == "__main__":
    main()
