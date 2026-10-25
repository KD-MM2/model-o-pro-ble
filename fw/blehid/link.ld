MEMORY { FLASH (rx) : ORIGIN = 0x40000, LENGTH = 0x8000
         RAM (rwx)  : ORIGIN = 0x2000B400, LENGTH = 0x2000 }
SECTIONS {
  .text : { KEEP(*(.entry)) *(.text*) *(.rodata*) } > FLASH
  .bss (NOLOAD) : { *(.bss*) *(COMMON) } > RAM
  /DISCARD/ : { *(.ARM.exidx*) *(.comment) *(.note*) }
}
