#!/usr/bin/env bash
# Instala kbdfx y da permiso a tu usuario para controlar la luz sin sudo.
set -e
cd "$(dirname "$0")"

echo "1/5 Instalando /usr/local/bin/kbdfx"
sudo install -m 755 kbdfx.py /usr/local/bin/kbdfx

echo "2/5 Regla udev (permiso de escritura para la luz del teclado y el logo)"
sudo tee /etc/udev/rules.d/90-kbdfx.rules >/dev/null <<'EOF'
ACTION=="add", SUBSYSTEM=="leds", KERNEL=="tpacpi::kbd_backlight", RUN+="/bin/chmod 0666 /sys/class/leds/%k/brightness"
ACTION=="add", SUBSYSTEM=="leds", KERNEL=="tpacpi::lid_logo_dot", RUN+="/bin/chmod 0666 /sys/class/leds/%k/brightness"
EOF
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=leds --action=add

echo "3/5 Servicio de usuario para arrancar con la sesion"
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/kbdfx@.service <<'EOF'
[Unit]
Description=Animacion del teclado ThinkPad (kbdfx %i)

[Service]
ExecStart=/usr/local/bin/kbdfx %i
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload

echo "4/5 Acceso directo en el menu de aplicaciones"
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/kbdfx.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Luces del teclado
Comment=Animaciones para la luz del teclado ThinkPad (kbdfx)
Exec=kbdfx
Icon=input-keyboard
Terminal=true
Categories=Utility;Settings;
EOF

echo "5/5 Extension de GNOME (boton 'Animacion' en los ajustes rapidos)"
UUID="kbdfx@kbdfx.local"
if command -v gnome-shell >/dev/null && [ -d "extension/$UUID" ]; then
    DEST=~/.local/share/gnome-shell/extensions/$UUID
    mkdir -p "$DEST"
    cp extension/$UUID/metadata.json extension/$UUID/extension.js "$DEST/"
    python3 - "$UUID" <<'PY'
import ast, subprocess, sys
uuid = sys.argv[1]
cur = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
                     capture_output=True, text=True).stdout.strip()
lista = ast.literal_eval(cur.replace("@as ", "")) if cur else []
if uuid not in lista:
    lista.append(uuid)
    subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(lista)])
PY
    gsettings set org.gnome.shell disable-user-extensions false
    EXT_OK=1
else
    echo "   (GNOME Shell no encontrado o falta la carpeta extension/: se omite)"
fi

echo
echo "Listo. Abre el menu con:  kbdfx"
echo "o busca 'Luces del teclado' en tus aplicaciones."
echo "Para que arranque solo:  systemctl --user enable --now kbdfx@teclear"
echo "Para quitarlo:           systemctl --user disable --now kbdfx@teclear"
if [ -n "$EXT_OK" ]; then
    echo
    echo "IMPORTANTE: cierra sesion y vuelve a entrar para ver el boton 'Animacion'"
    echo "en los ajustes rapidos (esquina superior derecha)."
fi
