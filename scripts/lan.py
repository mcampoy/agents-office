"""Turns on or off access to the office from the phone (same Wi-Fi). See server/lan.py.

Usage: py -3 scripts/lan.py [--enable | --disable | --new-key | --show] [--data FOLDER]

Changes apply when the office restarts: .\\start-office.ps1 -Stop and then .\\start-office.ps1.
The output is read by the user, so it is Spanish.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server import lan  # noqa: E402
from server.offices import read_projects  # noqa: E402
from server.profile import Profile, data_folder  # noqa: E402

FIREWALL = ('New-NetFirewallRule -DisplayName "agents-office" -Direction Inbound -Protocol TCP '
            '-LocalPort {port} -Action Allow -Profile Private')


def port_of(data):
    projects = read_projects(data)
    try:
        return Profile(projects[0]["profile"] if projects else None)["port"]
    except (OSError, ValueError):
        return 8765


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = p.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    group.add_argument("--new-key", action="store_true")
    group.add_argument("--show", action="store_true")
    p.add_argument("--data")
    args = p.parse_args()
    data = data_folder(args.data)
    port = port_of(data)
    if args.enable:
        lan.enable(data)
        print("Acceso desde el celular activado.")
    elif args.disable:
        lan.disable(data)
        print("Acceso desde el celular desactivado: la oficina vuelve a escuchar solo en esta computadora.")
    elif args.new_key:
        lan.new_key(data)
        print("Clave nueva: los celulares que ya habían entrado van a tener que ingresarla otra vez.")
    settings = lan.load(data)
    if not settings:
        print("Estado: desactivado. Para activarlo: py -3 scripts/lan.py --enable")
    else:
        ip = lan.primary_ip()
        print(f"Estado: activado. Clave: {settings['key']}")
        print(f"Desde el celular, conectado al mismo Wi-Fi: {lan.phone_url(ip or '<ip-de-esta-compu>', port, settings['key'])}")
        print("Usalo solo en un Wi-Fi de confianza (casa u oficina): el tráfico no va cifrado.")
        print("Si el celular no llega, Windows puede estar bloqueando el puerto. En una PowerShell de administrador:")
        print(f"  {FIREWALL.format(port=port)}")
        print("y verificá que la red Wi-Fi figure como privada (Configuración > Red e Internet).")
    if args.enable or args.disable or args.new_key:
        print("Reiniciá la oficina para aplicarlo: .\\start-office.ps1 -Stop y después .\\start-office.ps1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
