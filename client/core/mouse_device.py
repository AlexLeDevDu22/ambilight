"""
mouse_device.py – Pilotage HID direct de la Cougar Revenger ST (sans OpenRGB).

Protocole (repris du driver OpenRGB, validé sur la souris) : chaque écriture
est un feature report de 9 octets qui fixe UN registre :
    [0x00, 0xC4, 0x0F, 0x00, adresse, banque, valeur, 0x00, 0x00]
et [0x00, 0xC4, 0x03, 0x03, 0x03, …] valide une configuration d'effet.

Trois zones :
  0 = contour (plusieurs LEDs physiques, mais en mode Direct une seule couleur)
  1 = molette
  2 = logo
Le contour peut afficher plusieurs couleurs qui tournent via l'effet matériel
« Flow » (7 couleurs, vitesse 0x00 rapide → 0x0F lent, sens horaire/anti).
Les registres étant uniques, on ne réécrit que ce qui change (~0,7 ms/écriture).
"""

import threading

try:
    import ctypes
    import hid
    HID_OK = True
    # IMPORTANT : sur macOS, hidapi ouvre par défaut les périphériques en mode
    # EXCLUSIF (il « capture » la souris) → le curseur ne bouge plus. On force
    # l'ouverture partagée : les LEDs se pilotent pareil, la souris reste libre.
    try:
        ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(0)
    except (OSError, AttributeError):
        pass
except Exception:
    hid = None
    HID_OK = False

VID, PID = 0x12CF, 0x0412

# zone → (registre mode, banque)
_MODE_REG = {0: (0x77, 1), 1: (0x55, 0), 2: (0xE6, 0)}
# zone → (registre R en mode Direct, banque) ; luminosité = R - 1
_DIRECT_RGB = {0: (0x79, 1), 1: (0x57, 0), 2: (0xE8, 0)}

MODE_OFF = 0x00
MODE_DIRECT = 0x01
MODE_FLOW_CW = 0x09
MODE_FLOW_CCW = 0x0B

# Effet Flow du contour : 7 emplacements [luminosité, R, G, B] à partir de 0xAF
_FLOW_BASE, _FLOW_SPEED, _FLOW_BANK = 0xAF, 0xAD, 1
FLOW_SLOTS = 7


class RevengerST:
    def __init__(self):
        self._dev = None
        self._lock = threading.Lock()
        self._regs: dict[tuple[int, int], int] = {}
        self._zone_mode: dict[int, int] = {}
        self._flow_key = None
        self.connected = False
        self.status = "souris non détectée"

    # ------------------------------------------------------------------

    def open(self) -> bool:
        with self._lock:
            if self._dev is not None:
                return True
            if not HID_OK:
                self.status = "module hidapi manquant (pip install hidapi)"
                return False
            try:
                infos = [
                    d for d in hid.enumerate(VID, PID)
                    if d["interface_number"] == 0 and d["usage_page"] == 0x01 and d["usage"] == 0x02
                ]
            except Exception as e:
                self.status = f"HID indisponible : {e}"
                return False
            if not infos:
                self.status = "Cougar Revenger ST non détectée (branchée ?)"
                return False
            try:
                dev = hid.device()
                dev.open_path(infos[0]["path"])
            except Exception as e:
                self.status = f"accès à la souris refusé : {e}"
                return False
            self._dev = dev
            self._regs.clear()
            self._zone_mode.clear()
            self._flow_key = None
            self.connected = True
            self.status = "Cougar Revenger ST connectée"
            return True

    def close(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
        self._dev = None
        self.connected = False

    # ------------------------------------------------------------------

    def _write(self, addr: int, val: int, bank: int, force: bool = False):
        val = int(val) & 0xFF
        key = (bank, addr)
        if not force and self._regs.get(key) == val:
            return
        n = self._dev.send_feature_report([0x00, 0xC4, 0x0F, 0x00, addr & 0xFF, bank, val, 0x00, 0x00])
        if n is None or n < 0:
            raise OSError("écriture HID refusée")
        self._regs[key] = val

    def _apply(self):
        self._dev.send_feature_report([0x00, 0xC4, 0x03, 0x03, 0x03, 0x00, 0x00, 0x00, 0x00])

    def _set_zone_mode(self, zone: int, mode: int):
        if self._zone_mode.get(zone) != mode:
            reg, bank = _MODE_REG[zone]
            self._write(reg, mode, bank, force=True)
            self._zone_mode[zone] = mode
            if zone == 0:
                self._flow_key = None

    def _guard(self, fn, *args):
        """Exécute une opération HID ; en cas d'erreur la souris est considérée débranchée."""
        with self._lock:
            if self._dev is None:
                return False
            try:
                fn(*args)
                return True
            except Exception as e:
                self.status = f"souris déconnectée ({e.__class__.__name__}), reconnexion…"
                self._close_locked()
                return False

    # ------------------------------------------------------------------
    # API haut niveau (couleurs en entiers 0-255)
    # ------------------------------------------------------------------

    def set_direct(self, zone: int, rgb) -> bool:
        def op():
            self._set_zone_mode(zone, MODE_DIRECT)
            reg, bank = _DIRECT_RGB[zone]
            self._write(reg - 1, 255, bank)  # luminosité matérielle au max
            r, g, b = rgb
            self._write(reg, r, bank)
            self._write(reg + 1, g, bank)
            self._write(reg + 2, b, bank)
        return self._guard(op)

    def set_ring_flow(self, colors, speed: int, clockwise: bool, brightness: int = 255) -> bool:
        """Contour en effet matériel Flow. Ne reconfigure que si quelque chose change."""
        colors = [tuple(int(c) & 0xFF for c in col) for col in colors][:FLOW_SLOTS]
        while len(colors) < FLOW_SLOTS:
            colors.append(colors[len(colors) % max(1, len(colors))] if colors else (255, 255, 255))
        speed = max(0, min(15, int(speed)))
        key = (tuple(colors), speed, clockwise, int(brightness))
        if key == self._flow_key and self._zone_mode.get(0) in (MODE_FLOW_CW, MODE_FLOW_CCW):
            return True

        def op():
            mode = MODE_FLOW_CW if clockwise else MODE_FLOW_CCW
            reg, bank = _MODE_REG[0]
            self._write(reg, mode, bank, force=True)
            self._zone_mode[0] = mode
            off = _FLOW_BASE
            for (r, g, b) in colors:
                self._write(off + 1, r, _FLOW_BANK, force=True)
                self._write(off + 2, g, _FLOW_BANK, force=True)
                self._write(off + 3, b, _FLOW_BANK, force=True)
                off += 4
            self._write(_FLOW_SPEED, speed, _FLOW_BANK, force=True)
            off = _FLOW_BASE
            for _ in colors:
                self._write(off, brightness, _FLOW_BANK, force=True)
                off += 4
            self._apply()
            # Les registres Direct du contour doivent être réécrits au retour.
            for k in [k for k in self._regs if k[0] == 1 and 0x78 <= k[1] <= 0x7B]:
                del self._regs[k]
            self._flow_key = key
        return self._guard(op)

    def flow_active(self) -> bool:
        return self._zone_mode.get(0) in (MODE_FLOW_CW, MODE_FLOW_CCW)

    def all_off(self) -> bool:
        ok = True
        for z in (0, 1, 2):
            ok = self.set_direct(z, (0, 0, 0)) and ok
        return ok
