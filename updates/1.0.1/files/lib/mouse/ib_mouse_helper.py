# ib_mouse_helper.py
import ctypes
from ctypes import c_uint32, c_int32, c_bool, c_uint16, c_void_p
import atexit

class IbMouseHelper:
    # -----------------------------
    # Constants
    # -----------------------------
    SENDTYPE_LOGITECH = 2
    MOVEMODE_ABSOLUTE = 0
    MOVEMODE_RELATIVE = 1
    MOUSE_LEFT = 0x06
    MOUSE_RIGHT = 0x18
    MOUSE_MIDDLE = 0x60

    def __init__(self, dll_path=r"lib\mouse\IbInputSimulator.dll"):
        # Load DLL
        self.ibsim = ctypes.WinDLL(dll_path)

        # Setup prototypes
        self.ibsim.IbSendInit.argtypes = [c_uint32, c_uint32, c_void_p]
        self.ibsim.IbSendInit.restype = c_uint32

        self.ibsim.IbSendDestroy.argtypes = []
        self.ibsim.IbSendDestroy.restype = None

        self.ibsim.IbSendMouseMove.argtypes = [c_uint32, c_uint32, c_uint32]
        self.ibsim.IbSendMouseMove.restype = c_bool

        self.ibsim.IbSendMouseClick.argtypes = [c_uint32]
        self.ibsim.IbSendMouseClick.restype = c_bool

        self.ibsim.IbSendMouseWheel.argtypes = [c_int32]
        self.ibsim.IbSendMouseWheel.restype = c_bool

        self.ibsim.IbSendKeybdDown.argtypes = [c_uint16]
        self.ibsim.IbSendKeybdDown.restype = c_bool

        self.ibsim.IbSendKeybdUp.argtypes = [c_uint16]
        self.ibsim.IbSendKeybdUp.restype = c_bool

        self.ibsim.IbSendKeybdDownUp.argtypes = [c_uint16, ctypes.c_ubyte]
        self.ibsim.IbSendKeybdDownUp.restype = c_bool

        # Initialize Logitech driver
        result = self.ibsim.IbSendInit(self.SENDTYPE_LOGITECH, 0, None)
        if result != 0:
            raise RuntimeError(f"IbSendInit failed with code {result}")

        # Ensure cleanup at exit
        atexit.register(self.destroy)

    # -----------------------------
    # Mouse / Keyboard functions
    # -----------------------------
    def move(self, x: int, y: int, absolute=True) -> bool:
        mode = self.MOVEMODE_ABSOLUTE if absolute else self.MOVEMODE_RELATIVE
        result = self.ibsim.IbSendMouseMove(x, y, mode)
        return result

    def click(self, button=MOUSE_LEFT) -> bool:
        return self.ibsim.IbSendMouseClick(button)

    def wheel(self, delta: int) -> bool:
        return self.ibsim.IbSendMouseWheel(delta)

    def key_down(self, vk: int) -> bool:
        return self.ibsim.IbSendKeybdDown(vk)

    def key_up(self, vk: int) -> bool:
        return self.ibsim.IbSendKeybdUp(vk)

    def press_key(self, vk: int, modifiers: int = 0) -> bool:
        return self.ibsim.IbSendKeybdDownUp(vk, modifiers)

    def destroy(self):
        try:
            self.ibsim.IbSendDestroy()
        except Exception:
            pass

# -----------------------------
# Singleton instance (optional)
# -----------------------------
_mouse_helper_instance = None

def get_ib_mouse_helper(dll_path=None) -> IbMouseHelper:
    global _mouse_helper_instance
    if _mouse_helper_instance is None:
        _mouse_helper_instance = IbMouseHelper(dll_path) if dll_path else IbMouseHelper()
    return _mouse_helper_instance