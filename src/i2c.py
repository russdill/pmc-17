# Copyright (C) 2013 Russ Dill <Russ.Dill@gmail.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.

I2C_M_NOSTART = 0x01
I2C_M_RD = 0x02
I2C_M_RECV_LEN = 0x04
I2C_SMBUS_BLOCK_MAX = 0x20

class i2c(object):
    def __init__(self, hw):
        self.hw = hw

    def fill_recv_len(self, rlen):
        self.recv_len = rlen

    def make_buf(self, buf):
        def append(b):
            return buf.append(b)
        return append

    def xfer(self, *msgs):
        self.hw.start()
        first_msg = True
        self.hw.start()
        for msg in msgs:
            addr, flags, buf, rlen = msg
            if not flags & I2C_M_NOSTART:
                if not first_msg:
                    self.hw.repstart()
                self.hw.outb((addr << 1) | (1 if (flags & I2C_M_RD) else 0))
            if flags & I2C_M_RD:
                if flags & I2C_M_RECV_LEN or rlen is None:
                    self.hw.inb(self.fill_recv_len)
                    self.flush()
                    if self.hw.i2c_error or self.recv_len > I2C_SMBUS_BLOCK_MAX:
                        self.hw.acknak(False)
                        raise error()
                    self.hw.acknak(recv_len == 0)
                    buf.append(self.recv_len)
                    rlen = self.rec_len

                for i in range(0, rlen):
                    self.hw.inb(self.make_buf(buf))
                    self.hw.acknak(rlen - i > 1)
            else:
                for b in buf:
                    self.hw.outb(b)
            first_msg = False
        self.hw.stop()

    def flush(self):
        self.hw.flush_all()

    def master_send(self, addr, buf):
        self.xfer((addr, 0, buf, None))

    def master_recv(self, addr, buf, rlen):
        self.xfer((addr, I2C_M_RD, buf, rlen))

    def probe_func_quick_read(self, addr):
        self.xfer((addr, I2C_M_RD, None, 0))
        self.flush()

    def smbus_read_byte(self, addr):
        buf = []
        self.xfer((addr, I2C_M_RD, buf, 1))
        self.flush()
        return buf[0]

    def smbus_write_byte(self, addr, val):
        self.xfer((addr, 0, [val], None))
        self.flush()

    def smbus_read_byte_data(self, addr, cmd):
        buf = []
        self.xfer((addr, 0, [cmd], None), (addr, I2C_M_RD, buf, 1))
        self.flush()
        return buf[0]

    def smbus_write_byte_data(self, addr, cmd, val):
        self.xfer((addr, 0, [cmd, val], None))
        self.flush()

    def smbus_read_word_data(self, addr, cmd):
        buf = []
        self.xfer((addr, 0, [cmd], None), (addr, I2C_M_RD, buf, 2))
        self.flush()
        return buf[1] | buf[0] << 8

    def smbus_write_word_data(self, addr, cmd, val):
        self.xfer((addr, 0, [cmd, val >> 8, val & 0xff], None))
        self.flush()

    def smbus_read_block_data(self, addr, cmd):
        buf = []
        self.xfer((addr, 0, [cmd], None), (addr, I2C_M_RD, buf, None))
        self.flush()
        return buf[1:]

    def smbus_write_block_data(self, addr, cmd, buf):
        self.xfer((addr, 0, [cmd, len(buf)] + buf, None))
        self.flush()

    def smbus_read_i2c_block_data(self, addr, cmd, rlen):
        buf = []
        self.xfer((addr, 0, [cmd], None), (addr, I2C_M_RD, buf, rlen))
        self.flush()
        return buf[1:]

    def smbus_write_i2c_block_data(self, addr, cmd, buf):
        self.xfer((addr, 0, [cmd] + buf, None))
        self.flush()
