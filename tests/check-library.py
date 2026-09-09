"""Verify the dynamically loaded firmware API without booting a guest."""

import ctypes
import sys


library = ctypes.CDLL(sys.argv[1])
library.krunfw_get_version.argtypes = []
library.krunfw_get_version.restype = ctypes.c_int
assert library.krunfw_get_version() == 5, "unexpected firmware ABI"

library.krunfw_get_kernel.argtypes = [ctypes.POINTER(ctypes.c_size_t)] * 3
library.krunfw_get_kernel.restype = ctypes.c_void_p
load_address = ctypes.c_size_t()
entry_address = ctypes.c_size_t()
size = ctypes.c_size_t()
bundle = library.krunfw_get_kernel(
    ctypes.byref(load_address), ctypes.byref(entry_address), ctypes.byref(size)
)
assert bundle, "missing kernel bundle"
assert bundle % 65536 == 0, "kernel bundle is not aligned"
assert size.value > 0 and size.value % 65536 == 0, "invalid kernel bundle size"
assert load_address.value > 0, "missing kernel load address"
assert entry_address.value > 0, "missing kernel entry address"
assert any(ctypes.string_at(bundle, min(size.value, 4096))), "empty kernel data"
print(
    f"firmware ABI 5: kernel size={size.value}, "
    f"load={load_address.value:#x}, entry={entry_address.value:#x}"
)
