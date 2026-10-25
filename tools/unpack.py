import struct
def unpack(src, n):
    i=0; out=bytearray()
    while len(out)<n:
        t=src[i]; i+=1
        c=t&7
        if c==0: c=src[i]; i+=1
        z=t>>4
        if z==0: z=src[i]; i+=1
        out+=src[i:i+c-1]; i+=c-1
        if t&8:
            off=src[i]; i+=1
            for _ in range(z+2): out.append(out[-off])
        else:
            out+=bytes(z)
    return bytes(out), i
if __name__=='__main__':
    g=open('stock/golden_app.bin','rb').read();B=0x6000
    s=g[0x1c944-B:0x1cc90-B]
    d,used=unpack(s,0x8a8)
    print(len(d),used,len(s))
    open('build/init0.bin','wb').write(d[:0x8a8])
    for o in range(0,0x8a8,4):
        v=struct.unpack_from('<I',d,o)[0]
        if 0x6000<=v<0x1cc90: print(hex(0x20003000+o),hex(v))
