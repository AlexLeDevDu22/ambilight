"""Capture des couleurs autour de la souris et pilotage OpenRGB."""

import threading
import subprocess
import socket
from collections.abc import Sequence

import numpy as np
import time

from openrgb import OpenRGBClient
from openrgb.utils import DeviceType, RGBColor
OpenRGBClient.update_plugins = lambda self: None # skip plugin update and it faster

RGB = tuple[int, int, int]
Position = tuple[float | None, float | None]

OPENRGB_PATH = "/Applications/OpenRGB.app/Contents/MacOS/OpenRGB"
OPENRGB_HOST = "127.0.0.1"
OPENRGB_PORT = 6742

def get_mouse_position(screen_index: int) -> Position:
	"""Renvoie les coordonnees locales du curseur sur l'ecran, sinon None."""
	try:
		import Quartz.CoreGraphics as CG

		error, display_ids, count = CG.CGGetActiveDisplayList(16, None, None)
		if error != 0 or not 0 <= screen_index < count:
			return None, None

		event = CG.CGEventCreate(None)
		if event is None:
			return None, None

		position = CG.CGEventGetLocation(event)
		bounds = CG.CGDisplayBounds(display_ids[screen_index])
		x = position.x - bounds.origin.x
		y = position.y - bounds.origin.y
		if not (0 <= x < bounds.size.width and 0 <= y < bounds.size.height):
			return None, None
		return x, y
	except Exception:
		return None, None


def _mouse_led_layout(led_names: Sequence[str]) -> list[tuple[float, float]]:
	"""Approxime le contour du Revenger ST; OpenRGB ne donne pas ses XY."""
	count = len(led_names)
	if count == 0:
		return []

	if count == 1:
		points = [(0.5, 0.82)]
	elif count == 2:
		points = [(0.5, 0.08), (0.5, 0.88)]
	else:
		side_count = count - 2
		points = [(0.5, 0.08)]
		for index in range(side_count):
			angle = np.deg2rad(225 - 270 * (index + 0.5) / side_count)
			points.append((0.5 + 0.5 * np.cos(angle), 0.5 + 0.5 * np.sin(angle)))
		points.append((0.5, 0.88))

	for index, name in enumerate(led_names):
		normalized_name = name.lower()
		if "wheel" in normalized_name or "scroll" in normalized_name:
			points[index] = (0.5, 0.08)
		elif "logo" in normalized_name:
			points[index] = (0.5, 0.88)
	return points


def sample_mouse_colors(
	frame: np.ndarray,
	position: Position,
	radius_px: int,
	led_names: Sequence[str],
	downscale: int = 1,
) -> list[RGB]:
	"""Moyenne un petit disque d'image pour chaque position de LED."""
	if not led_names:
		return []
	if position[0] is None or position[1] is None:
		return [(0, 0, 0)] * len(led_names)
	if frame.ndim != 3 or frame.shape[2] < 3:
		raise ValueError("frame doit etre une image RGB")

	scale = max(1, downscale)
	center_x = int(round(position[0] / scale))
	center_y = int(round(position[1] / scale))
	radius = max(1, int(round(max(1, radius_px) / scale)))
	average_radius = max(1, radius // 7)
	height, width = frame.shape[:2]
	colors: list[RGB] = []

	for normalized_x, normalized_y in _mouse_led_layout(led_names):
		sample_x = center_x + int(round((normalized_x - 0.5) * radius * 1.5))
		sample_y = center_y + int(round((normalized_y - 0.5) * radius * 1.8))
		left = max(0, sample_x - average_radius)
		right = min(width, sample_x + average_radius + 1)
		top = max(0, sample_y - average_radius)
		bottom = min(height, sample_y + average_radius + 1)
		if left >= right or top >= bottom:
			colors.append((0, 0, 0))
			continue

		rows, columns = np.ogrid[top:bottom, left:right]
		disk = (rows - sample_y) ** 2 + (columns - sample_x) ** 2 <= average_radius**2
		pixels = frame[top:bottom, left:right, :3][disk]
		if pixels.size == 0:
			colors.append((0, 0, 0))
		else:
			average = np.rint(pixels.mean(axis=0)).astype(int)
			colors.append((int(average[0]), int(average[1]), int(average[2])))

	return colors

def is_openrgb_server_running() -> bool:
    """Vérifie si un serveur OpenRGB écoute sur le port 6742."""
    try:
        with socket.create_connection(
            (OPENRGB_HOST, OPENRGB_PORT),
            timeout=0.2,
        ):
            return True
    except OSError:
        return False


def wait_for_openrgb_server(timeout: float = 5.0) -> bool:
    """Attend que le serveur OpenRGB soit disponible."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if is_openrgb_server_running():
            return True
        time.sleep(0.1)

    return False

class MouseAmbient:
	"""Envoie les couleurs echantillonnees au peripherique souris OpenRGB."""

	def __init__(self):
		self.status = "OpenRGB : en attente"
		self.led_count = 0
		self._lock = threading.Lock()
		self._stop_event = threading.Event()
		self._latest: tuple[np.ndarray, Position, int, int] | None = None
		self._thread: threading.Thread | None = None


	def start(self) -> None:
		if self._thread and self._thread.is_alive():
			return
		self._stop_event.clear()
		self._thread = threading.Thread(
			target=self._run,
			daemon=True,
		)

		# Ne lance OpenRGB que si aucun serveur n'est déjà disponible.
		if not is_openrgb_server_running():
			try:
				self.cmd_openrgb = subprocess.Popen(
					[
						OPENRGB_PATH,
						"--server",
					],
					stdout=subprocess.DEVNULL,
					stderr=subprocess.DEVNULL,
				)
			except OSError as error:
				self.status = f"Impossible de lancer OpenRGB : {error}"
				return

			if not wait_for_openrgb_server():
				self.status = "OpenRGB lancé, mais serveur non disponible"
				return
		else:
			# Le serveur existait déjà : on ne le tuera pas dans stop().
			self.cmd_openrgb = None

		self._thread.start()

	def update_frame(
		self,
		frame: np.ndarray,
		position: Position,
		radius_px: int,
		downscale: int = 1,
	) -> None:
		with self._lock:
			self._latest = (frame, position, radius_px, downscale)

	def stop(self) -> None:
		self._stop_event.set()

		if self._thread:
			self._thread.join(timeout=2.0)
			self._thread = None

		# On ne ferme OpenRGB que si NOTRE instance a été lancée.
		if self.cmd_openrgb is not None:
			try:
				self.cmd_openrgb.terminate()
				self.cmd_openrgb.wait(timeout=2.0)
			except Exception:
				try:
					self.cmd_openrgb.kill()
				except Exception:
					pass
			finally:
				self.cmd_openrgb = None

	def _run(self) -> None:
		while not self._stop_event.is_set():
			client = None
			try:
				client = OpenRGBClient(name="Ambilight Mouse", port=OPENRGB_PORT, address=OPENRGB_HOST, protocol_version=4)
				mice = client.get_devices_by_type(DeviceType.MOUSE)
				device = next(
					(item for item in mice if "revenger" in item.name.lower()),
					next((item for item in mice if "cougar" in item.name.lower()), None),
				)
				if device is None:
					self.led_count = 0
					self.status = "Souris Cougar Revenger ST absente d'OpenRGB"
					self._stop_event.wait(5.0)
					continue

				led_names = [led.name for led in device.leds]
				self.led_count = len(led_names)
				if not led_names:
					self.status = f"{device.name} detectee, mais sans LED pilotable"
					self._stop_event.wait(5.0)
					continue

				device.set_custom_mode()
				self.status = f"{device.name} : {self.led_count} LED(s)"
				previous_colors: list[RGB] | None = None

				while not self._stop_event.wait(1 / 30):
					with self._lock:
						latest = self._latest
					if latest is None:
						continue

					frame, position, radius_px, downscale = latest
					colors = sample_mouse_colors(
						frame, position, radius_px, led_names, downscale
					)
					if colors == previous_colors:
						continue
					device.set_colors(
						[RGBColor(*color) for color in colors], fast=True
					)
					previous_colors = colors
			except Exception as error:
				self.status = f"SDK OpenRGB indisponible: {error}"
				self._stop_event.wait(5.0)
			finally:
				if client is not None:
					try:
						client.disconnect()
					except Exception:
						pass
