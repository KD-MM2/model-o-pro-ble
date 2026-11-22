"""swd.py -- SWD helpers shared by the flashing tools (pyocd with the generic cortex_m target, so ST-Link V2 clones work).
NVMC page erase / word write with read-back. The helpers refuse anything outside the 1 MB flash: UICR is never written,
and there is no chip erase."""
import time
from pyocd.core.helpers import ConnectHelper

PAGE = 0x1000
NVMC_READY, NVMC_CONFIG, NVMC_ERASEPAGE = 0x4001E400, 0x4001E504, 0x4001E508
AIRCR = 0xE000ED0C

def connect():
    s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach',
                                                         'frequency': 1000000})
    s.open()
    assert s.target.read32(0x10000100) == 0x52840, 'not an nRF52840 (FICR.INFO.PART)'
    return s

def stop(t):
    """Reset and halt on the first instruction. The reset clears the bootloader's flash write protection (ACL, set
    before it starts the app) and stops the SoftDevice cleanly; nothing runs while the tools write."""
    t.reset_and_halt()

def reset(t):
    t.write32(AIRCR, 0x05FA0004)    # SYSRESETREQ
    time.sleep(0.3)

def _wait(t):
    n = 0
    while not t.read32(NVMC_READY):
        n += 1
        assert n < 100000, 'NVMC timeout'

def _flash_only(lo, hi):
    assert 0 <= lo <= hi < 0x100000, 'refusing %#x-%#x: flash only, never UICR' % (lo, hi)

def erase_page(t, base):
    _flash_only(base, base + PAGE - 1)
    assert base % PAGE == 0
    t.write32(NVMC_CONFIG, 2); _wait(t)
    t.write32(NVMC_ERASEPAGE, base); _wait(t)
    t.write32(NVMC_CONFIG, 0); _wait(t)
    assert all(w == 0xFFFFFFFF for w in t.read_memory_block32(base, PAGE // 4)), \
        'page %#x not erased (write-protected? the tools reset the chip first for that reason)' % base

def write_words(t, addr, words):
    """Program words into erased flash, then read them back."""
    _flash_only(addr, addr + 4 * len(words) - 1)
    t.write32(NVMC_CONFIG, 1); _wait(t)
    for i, w in enumerate(words):
        if w != 0xFFFFFFFF:
            t.write32(addr + 4 * i, w); _wait(t)
    t.write32(NVMC_CONFIG, 0); _wait(t)
    got = t.read_memory_block32(addr, len(words))
    bad = [hex(addr + 4 * i) for i in range(len(words)) if got[i] != words[i]]
    assert not bad, 'verify failed at %s' % bad[:4]

def program_page(t, base, data):
    """Erase the page at base and write data (dict address -> byte); bytes not in data become 0xFF."""
    erase_page(t, base)
    words = []
    for off in range(0, PAGE, 4):
        w = 0xFFFFFFFF
        for k in range(4):
            a = base + off + k
            if a in data:
                w = (w & ~(0xFF << (8 * k))) | (data[a] << (8 * k))
        words.append(w)
    write_words(t, base, words)

def page_differs(t, base, data):
    """True if any byte of data (dict address -> byte) in this page differs from the chip."""
    cur = bytes(t.read_memory_block8(base, PAGE))
    return any(cur[a - base] != v for a, v in data.items() if base <= a < base + PAGE)

def pages_of(data):
    return sorted({a // PAGE * PAGE for a in data})
