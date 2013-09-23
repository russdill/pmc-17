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
import usb

scl = 0
sda_out = 1
sda_in = 2
alert = 4
nvouten = 5
sws = [7, 6]
addrs = [ 11, 10, 9, 8 ]
gpios = [ 15, 14, 13, 12 ]

def bit(b):
    return 1 << b

initial_output = (bit(addrs[0]) | bit(addrs[1]) | bit(addrs[2]) | bit(addrs[3]) |
                  bit(nvouten) | bit(sws[0]) | bit(sws[1]))

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
    def __init__(self, serial=None, index=None):
        self.ftdic = ftdi.ftdi_context()
        self.ftdi = ftdi
        self.sensors = dict()
        self.hw_sw = dict()
        self.hw_sw["DC"] = nvouten
        self.hw_sw["SW0"] = sws[0]
        self.hw_sw["SW1"] = sws[1]
        self.hw_sw["ALERT"] = alert
        self.hw_sw["GPIO0"] = gpios[0]
        self.hw_sw["GPIO1"] = gpios[1]
        self.hw_sw["GPIO2"] = gpios[2]
        self.hw_sw["GPIO3"] = gpios[3]
        self.switches = dict()

        try:
            ret = ftdi.ftdi_init(self.ftdic)
            if ret < 0:
                raise Exception
            ret = ftdi.ftdi_usb_open_desc_index(self.ftdic, 0x0403, 0x06010, "PMC-17 v1.0", serial, index if index else 0)
            if ret < 0:
                raise Exception("Could not open device", ftdi.ftdi_get_error_string(self.ftdic))
            ret = ftdi.ftdi_set_interface(self.ftdic, ftdi.INTERFACE_A)
            if ret < 0:
                raise Exception
            self.hw = i2c_ftdi.i2c_ftdi(self.ftdic, scl, sda_out, sda_in, 400000, initial_output)
            self.i2c = i2c.i2c(self.hw)
        except Exception as e:
            ftdi.ftdi_deinit(self.ftdic)
            raise

    def get_flag(self, sw, flag, default=False):
        if sw.lower() in self.switches:
            sw = self.switches[sw.lower()]
        for i in sw.split(',')[1:]:
            f, _, v = i.partition("=")
            if f.lower() == flag.lower():
                return v if len(v) else True
        return default

    def get_bit(self, sw):
        if sw.lower() in self.switches:
            sw = self.switches[sw.lower()]
        return self.hw_sw[sw.split(',')[0]]

    def set_output(self, sw_list, val):
        update_low = False
        update_high = False
        for sw in sw_list:
            v = val
            if self.get_flag(sw, 'active_low'):
                v = not v
            bit = self.get_bit(sw)
            self.hw.gpio_output(bit)
            self.hw.gpio_set(bit, v)
            update_low |= bit < 8
            update_high |= bit > 7
        if update_low:
            self.hw.gpio_update(False)
        if update_high:
            self.hw.gpio_update(False)
        self.hw.flush_all()

    def on(self, sw):
        self.set_output(sw, True)

    def off(self, sw):
        self.set_output(sw, False)

    def toggle(self, sw_list):
        update_low = False
        update_high = False
        max_delay = 0
        for sw in sw_list:
            bit = self.get_bit(sw)
            val = self.get_flag(sw, 'active_low')
            self.hw.gpio_output(bit)
            self.hw.gpio_set(bit, val)
            update_low |= bit < 8
            update_high |= bit > 7
            max_delay = max(max_delay, float(self.get_flag(sw, 'toggle', 0.010)))
        if update_low:
            self.hw.gpio_update(False)
        if update_high:
            self.hw.gpio_update(False)
        self.hw.delay(max_delay)
        for sw in sw_list:
            self.hw.gpio_set(bit, not val)
        self.hw.flush_all()
        if update_low:
            self.hw.gpio_update(False)
        if update_high:
            self.hw.gpio_update(False)

    def read_sw(self, sw_list):
        for sw in sw_list:
            bit = self.get_bit(sw)
            rh = self.get_flag(sw, 'reset_high')
            rl = self.get_flag(sw, 'reset_low')
            if rh or rl:
                self.hw.gpio_output(bit)
                self.hw.gpio_set(bit, rh)
                self.hw.gpio_update(bit > 7)
            self.hw.gpio_input(bit)
            self.hw.gpio_update(bit > 7)
            val = self.hw.gpio_value(bit)
            status = val
            if self.get_flag(sw, 'active_low'):
                status = not status
            print "{} {} ({})".format(sw.split(',')[0], "on" if status else "off", val)

    def add_switch(self, sw_name, info):
        name, _, info = info.lower().partition(',')
        if len(info):
            info = sw_name + "," + info
        else:
            info = sw_name
        self.switches[name.lower()] = info

    def add_sensor(self, name, addr, r=None, mux_addr=None):
        self.sensors[name] = reading(addr, r, mux_addr)

    def addr(self, a):
        for i in range(0, 4):
            self.hw.gpio_set(addrs[i], (a >> i) & 1)
        self.hw.gpio_update(True)

    def read(self, channels):
        for chan in channels:
            if chan not in self.hw_sw:
                self.sensors[chan].queue_read(self)
        self.i2c.flush()
        for chan in channels:
            if chan not in self.hw_sw:
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
    parser.add_argument('-s', '--serial', type=str, required=False)
    parser.add_argument('-i', '--index', type=int, required=False)
    parser.add_argument('-l', '--list', action="store_true")
    parser.add_argument("command", nargs="*")

    args = parser.parse_args()

    if args.list:
        index = 0
        for bus in usb.busses():
            for dev in bus.devices:
                if dev.idVendor != 0x0403 or dev.idProduct != 0x6010:
                    continue
                handle = dev.open()
                print "{}/{}: index={}, serial={}".format(bus.dirname, dev.devnum, index, handle.getString(dev.iSerialNumber, 1024))
                index += 1
        exit()

    points = dict()
    mappings = collections.OrderedDict()
    if args.mapping is not None:
        parse_file(args.mapping, 0, points, mappings)
    else:
        for i in range(0, 16):
            mappings["CH" + str(i)] = None

    points["pmc.DC_IN"] = 0.050
    mappings["CH16"] = "pmc.DC_IN"

    device = pmc(args.serial, args.index)
    point_len = len("Total Power")
    name_len = 0
    for name, point in mappings.items():
        if name in device.hw_sw:
            device.add_switch(name, point)
            continue
        name_len = max(name_len, len(name))
        r = None if point is None else points[point]
        point_len = max(point_len, 0 if point is None else len(point))
        if name == "CH16":
            addr = 0x4e
            mux_addr = None
        elif name[:2] == "CH":
            addr = 0x4f
            mux_addr = int(name[2:])
        else:
            addr = int(name, 0)
            mux_addr = None
        device.add_sensor(name, addr, r, mux_addr)

    device.add_switch("DC", "pmc.POWER,active_low,toggle=0.250")

    if args.command:
        if args.command[0] == 'toggle':
            device.toggle(args.command[1:])
        elif args.command[0] == 'on':
            device.on(args.command[1:])
        elif args.command[0] == 'off':
            device.off(args.command[1:])
        elif args.command[0] == 'read':
            device.read_sw(args.command[1:])
    else:
        device.read(mappings.keys())
        total = 0
        for name, point in mappings.items():
            if name not in device.sensors:
                continue
            s = device.sensors[name]
            if point is not None:
                if name != "CH16":
                    total += s.power
                print "({name:>{name_len}}) {point:<{point_len}} {bus}V * {current}A = {power}W".format(
                    name=name, name_len=name_len, point=point, point_len=point_len,
                    bus=print_si(s.bus), current=print_si(s.current), power=print_si(s.power))
            else:
                print "({name:>{name_len}}) {point:<{point_len}} {bus}V   {shunt}V".format(
                    name=name, name_len=name_len, point=point, point_len=point_len,
                    bus=print_si(s.bus), shunt=print_si(s.shunt))

        remainder = device.sensors["CH16"].power - total

        print " {empty:>{name_len}}  {point:<{point_len}} {empty:<23} {power}W".format(
            empty="", name_len=name_len, point="Total power", point_len=point_len,
            power=print_si(total))

        print " {empty:>{name_len}}  {point:<{point_len}} {empty:<23} {power}W".format(
            empty="", name_len=name_len, point="Remainder", point_len=point_len,
            power=print_si(remainder))
