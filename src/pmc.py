#!/usr/bin/env python
#
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
import i2c_ftdi
import i2c
import time
import collections
import argparse
import math

class reading(object):
    def __init__(self, addr, r, mux_addr=None):
        self.addr = addr
        self.r = r
        self.mux_addr = mux_addr

    def queue_read(self, p):
        self.bus_buf = []
        self.shunt_buf = []
        if self.mux_addr is not None:
            p.addr(self.mux_addr)
            p.hw.delay(0.001)
            p.i2c.xfer((self.addr, 0, [0, 0x41, 0x23], None))
            p.hw.delay(0.0011)
        p.i2c.xfer((self.addr, 0, [1], None),
                   (self.addr, i2c.I2C_M_RD, self.shunt_buf, 2))
        if self.mux_addr is not None:
            p.hw.delay(0.0011)
        p.i2c.xfer((self.addr, 0, [2], None),
                   (self.addr, i2c.I2C_M_RD, self.bus_buf, 2))

    def fin(self):
        shunt_v = self.shunt_buf[1] | self.shunt_buf[0] << 8
        self.shunt_v = shunt_v
        bus_v = self.bus_buf[1] | self.bus_buf[0] << 8

        if shunt_v >= 0x8000:
            shunt_v = shunt_v - 0x10000

        self.shunt = shunt_v / 400000.0
        self.bus = bus_v / 800.0
        self.current = None if self.r is None else self.shunt / self.r
        self.power = None if self.r is None else self.current * self.bus

class pmc(object):
    def __init__(self):
        self.ftdic = ftdi.ftdi_context()
        self.ftdi = ftdi
        self.sensors = dict()
        try:
            ret = ftdi.ftdi_init(self.ftdic)
            if ret < 0:
                raise Exception
            ret = ftdi.ftdi_usb_open_desc(self.ftdic, 0x0403, 0x06010, "PMC-17 v1.0", None)
            if ret < 0:
                raise Exception
            ret = ftdi.ftdi_set_interface(self.ftdic, ftdi.INTERFACE_A)
            if ret < 0:
                raise Exception
            self.hw = i2c_ftdi.i2c_ftdi(self.ftdic, 0, 1, 2, 400000, 0xf00)
            self.i2c = i2c.i2c(self.hw)
        except Exception as e:
            ftdi.ftdi_deinit(self.ftdic)
            raise

    def add_sensor(self, name, addr, r=None, mux_addr=None):
        self.sensors[name] = reading(addr, r, mux_addr)

    def addr(self, a):
        for i in range(0, 4):
            self.hw.gpio_set(8 + i, (a >> (3 - i)) & 1)
        self.hw.gpio_update(True)

    def read(self, channels):
        for chan in channels:
            self.sensors[chan].queue_read(self)
        self.i2c.flush()
        for chan in channels:
            self.sensors[chan].fin()

def parse_file(f, depth, points, mappings):
    if depth > 100:
        raise Exception("includes nested too deep, circular include?")
    for line in f:
        line = line.partition('#')[0].strip()
        if not len(line):
            continue
        key, val = line.split(None, 1)
        if key.lower() == "include":
            parse_file(open(val), depth + 1, points, mappings)
        else:
            try:
                r = float(val)
                points[key] = r
            except:
                mappings[key] = val

def print_si(val, sig=5):
    digits = math.floor(math.log10(abs(val))) if val else 0
    exp = int(digits // 3)
    digits = int(digits) % 3 + 1
    si = ''
    if exp >= -5 and exp <= 4:
        si = 'fpnum kMGT'[exp + 5]
        val /= math.pow(10, exp * 3)
    return '{: {}.{}f}{}'.format(val, digits, sig - digits, si)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(conflict_handler='resolve')
    parser.add_argument('-m', '--mapping', type=argparse.FileType('rb'), required=False)

    args = parser.parse_args()

    points = dict()
    mappings = collections.OrderedDict()
    points["pmc.DC_IN"] = 0.050
    mappings["CH0"] = "pmc.DC_IN"
    if args.mapping is not None:
        parse_file(args.mapping, 0, points, mappings)
    else:
        for i in range(0, 16):
            mappings["CH" + str(i + 1)] = None

    device = pmc()
    point_len = len("Total Power")
    name_len = 0
    for name, point in mappings.items():
        name_len = max(name_len, len(name))
        r = None if point is None else points[point]
        point_len = max(point_len, 0 if point is None else len(point))
        if name == "CH0":
            addr = 0x4e
            mux_addr = None
        elif name[:2] == "CH":
            addr = 0x4f
            mux_addr = int(name[2:]) - 1
        else:
            addr = int(name, 0)
            mux_addr = None
        device.add_sensor(name, addr, r, mux_addr)

    device.read(mappings.keys())
    total = 0
    for name, point in mappings.items():
        s = device.sensors[name]
        if point is not None:
            if name != "CH0":
                total += s.power
            print "({name:>{name_len}}) {point:<{point_len}} {bus}V * {current}A = {power}W".format(
                name=name, name_len=name_len, point=point, point_len=point_len,
                bus=print_si(s.bus), current=print_si(s.current), power=print_si(s.power))
        else:
            print "({name:>{name_len}}) {point:<{point_len}} {bus}V   {shunt}V".format(
                name=name, name_len=name_len, point=point, point_len=point_len,
                bus=print_si(s.bus), shunt=print_si(s.shunt))

    remainder = device.sensors["CH0"].power - total

    print " {empty:>{name_len}}  {point:<{point_len}} {empty:<23} {power}W".format(
        empty="", name_len=name_len, point="Total power", point_len=point_len,
        power=print_si(total))

    print " {empty:>{name_len}}  {point:<{point_len}} {empty:<23} {power}W".format(
        empty="", name_len=name_len, point="Remainder", point_len=point_len,
        power=print_si(remainder))
