# Minimal openMSX probe for agent runs.
#   MSX_PROBE_INIT=0x4010 MSX_PROBE_OUT=/tmp/probe.log \
#   openmsx -carta /abs/game.rom -script thisfile.tcl
#
# Creates a BP at INIT (or MSX_PROBE_INIT), logs regs/disasm on hit, exits.

set out_path "/tmp/msx-openmsx-probe.log"
catch { set out_path $::env(MSX_PROBE_OUT) }
set init_addr 0x4010
catch { set init_addr $::env(MSX_PROBE_INIT) }

set fh [open $out_path w]
puts $fh "openmsx_boot_probe"
puts $fh "init_addr=$init_addr"

proc plog {msg} {
    global fh
    puts $fh $msg
    flush $fh
}

# Address breakpoint; on hit log and quit after a short settle.
set bp [debug breakpoint create $init_addr]
plog "breakpoint=$bp"

debug set_bp $init_addr {
    plog [format "HIT pc=%04X sp=%04X a=%02X hl=%04X" [reg pc] [reg sp] [reg a] [reg hl]]
    catch { plog "disasm=[debug disasm [reg pc]]" }
    catch { plog "slotmap=[slotmap]" }
    plog "done"
    close $::fh
    exit
}

# Safety timeout if INIT never hit (wrong address / no cart)
after time 8 {
    plog "timeout without breakpoint hit; pc=[reg pc]"
    catch { plog "disasm=[debug disasm [reg pc]]" }
    catch { close $::fh }
    exit
}
