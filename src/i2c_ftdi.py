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

import ftdi
import math
from ctypes import c_uint, pointer

class i2c_ftdi(object):
    def __init__(self, ftdic, scl, sda_out, sda_in, speed_hz, direction):
        direction |= (1 << scl) | (1 << sda_out)
        direction &= ~(1 << sda_in)

        self.ftdic = ftdic
        self.scl = scl
        self.sda_out = sda_out
        self.dir = direction
        self.wr_buffer = bytearray()
        self.dest = []
        self.i2c_error = False
        self.hw_error = 0
        self.gpio = 0

        ret = ftdi.ftdi_set_bitmode(ftdic, direction & 0xff, ftdi.BITMODE_MPSSE)
        if ret < 0:
            raise Exception("ftdi_set_bitmode failed", ret)

        self.cmd(ftdi.GET_BITS_LOW)
        self.dest.append(lambda b: self.read_initial(b, False))
        self.cmd(ftdi.GET_BITS_HIGH)
        self.dest.append(lambda b: self.read_initial(b, True))
        self.flush_all()

        self.set_rate(speed_hz)

        self.cmd(ftdi.DIS_ADAPTIVE)
        self.cmd(ftdi.EN_3_PHASE)
        self.three_phase = True        
        self.append_data_clock((1, 1))

        self.flush_all()

    def read_initial(self, b, high):
        self.gpio |= (b << 8) if high else b

    def flush_input(self):
        while len(self.dest) and not self.hw_error:

            data = chr(0)*len(self.dest)
            ret = ftdi.ftdi_read_data(self.ftdic, data, len(self.dest))
            if ret < 0:
                self.hw_error = ret
                self.i2c_error = True
                break

            for b in data[:ret]:
                self.dest.pop(0)(ord(b))

    def flush_output(self):
        if self.hw_error or not len(self.wr_buffer):
            return
        buf = None
        for i in self.wr_buffer:
            if buf is None:
                buf = chr(i)
            else:
                buf += chr(i)
        ret = ftdi.ftdi_write_data(self.ftdic, buf, len(self.wr_buffer))
        if ret < 0:
            self.hw_error = ret
            self.i2c_error = True
        self.wr_buffer = bytearray()

    def flush_all(self):
        self.flush_output()
        self.flush_input()

    def gpio_update(self, high):
        if self.hw_error:
            raise Exception(self.hw_error)
        if high:
            self.cmd(ftdi.SET_BITS_HIGH, self.gpio >> 8, self.dir >> 8)
        else:
            self.cmd(ftdi.SET_BITS_LOW, self.gpio & 0xff, self.dir & 0xff)

    def gpio_output(self, gpio):
        self.dir |= 1 << gpio

    def gpio_input(self, gpio):
        self.dir &= ~(1 << gpio)

    def gpio_dir(self, gpio, output):
        if output:
            self.dir |= 1 << gpio
        else:
            self.dir &= ~(1 << gpio)

    def gpio_value(self, gpio):
        def assign(b, bit):
            gpio_value.ret = (b >> bit) & 1

        if gpio > 7:
            self.cmd(ftdi.GET_BITS_HIGH)
            self.dest.append(lambda b: assign(b, gpio - 8))
        else:
            self.cmd(ftdi.GET_BITS_LOW)
            self.dest.append(lambda b: assign(b, gpio))
        self.flush_all()

        return gpio_value.ret

    def gpio_low(self, gpio):
        self.gpio &= ~(1 << gpio)

    def gpio_high(self, gpio):
        self.gpio |= 1 << gpio

    def gpio_set(self, gpio, val):
        if val:
            self.gpio |= 1 << gpio
        else:
            self.gpio &= ~(1 << gpio)

    def append_data_clock(self, *args):
        for arg in args:
            data, clk = arg
            self.gpio_dir(self.sda_out, data is not None)
            self.gpio_set(self.sda_out, data == True)
            self.gpio_set(self.scl, clk)
            self.gpio_update(False)

    def cmd2(self, cmd, data):
        self.wr_buffer.extend([cmd, data & 0xff, data >> 8])

    def cmd(self, cmd, *args):
        self.wr_buffer.extend([cmd] + list(args))

    def set_rate(self, hz):
        self.hz = hz
        numerator = 30000000;
        if hz >= 60000000:
            self.cmd(ftdi.DIS_DIV_5)
        else:
            self.cmd(ftdi.EN_DIV_5)
            numerator /= 5
        divisor = numerator / hz - 1
        self.cmd2(ftdi.TCK_DIVISOR, divisor)

    def delay(self, seconds):
        m = self.hz / 8.0
        if self.three_phase:
            m /= 1.5
        ticks = int(math.ceil(seconds * m))
        while ticks:
            n = min(ticks, 0x10000)
            ticks -= n
            self.cmd2(ftdi.CLK_BYTES, n - 1)

    def start(self):
        self.i2c_error = False
        self.append_data_clock((0, 1))

    def repstart(self):
        self.append_data_clock((0, 0), (1, 1), (0, 1))

    def stop(self):
        self.append_data_clock((0, 0), (0, 1), (1, 1))

    def acknak(self, val):
        self.cmd(ftdi.MPSSE_DO_WRITE | ftdi.MPSSE_WRITE_NEG | ftdi.MPSSE_BITMODE, 0, 0 if val else 0x80)

    def apply_nack(self, b):
        if b & 1:
            self.i2c_error = True
            raise Exception("I2C error")

    def outb(self, byte):
        self.append_data_clock((0, 0))
        self.cmd(ftdi.MPSSE_DO_WRITE | ftdi.MPSSE_WRITE_NEG | ftdi.MPSSE_BITMODE, 7, byte)
        self.append_data_clock((None, 0))
        self.cmd(ftdi.MPSSE_DO_READ | ftdi.MPSSE_BITMODE, 0)
        self.dest.append(self.apply_nack)

    def inb(self, func):
        self.append_data_clock((None, 0))
        self.cmd2(ftdi.MPSSE_DO_READ, 0)
        self.append_data_clock((0, 0))
        self.dest.append(func)
