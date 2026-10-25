import sys,struct
from capstone import *
g=open('stock/golden_app.bin','rb').read();B=0x6000
md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS|CS_MODE_V8); md.detail=True
def dis(a,n=0x40,show=True):
    out=[]
    for i in md.disasm(g[a-B:a-B+n],a):
        out.append(f'{i.address:x}: {i.mnemonic} {i.op_str}')
    if show: print('\n'.join(out))
    return out
def bl_xrefs(target):
    r=[]
    for o in range(0,len(g)-3,2):
        for i in md.disasm(g[o:o+4],B+o):
            if i.mnemonic in('bl','b.w') and i.operands and i.operands[0].imm==target: r.append((i.address,i.mnemonic))
            break
    return r
if __name__=='__main__':
    if sys.argv[1]=='x':
        for t in sys.argv[2:]: print(t,[ (hex(a),m) for a,m in bl_xrefs(int(t,16))])
    else: dis(int(sys.argv[1],16),int(sys.argv[2],16) if len(sys.argv)>2 else 0x40)
