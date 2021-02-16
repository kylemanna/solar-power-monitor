#!/usr/bin/env python3
"""Solar Power Monitor built around a INA3221"""
import datetime
import json
import sched
import smbus
import time
import struct


class INA3221():
    """Driver class for interfacing to a Texas Instruments INA3221 Voltage and Current Monitor
    """

    INA3221_ADDRESS = 0x40 # A0+A1=GND

    INA3221_REG_CONFIG           = 0x00
    INA3221_REG_SHUNTVOLTAGE_1   = 0x01
    INA3221_REG_BUSVOLTAGE_1     = 0x02
    INA3221_REG_SHUNTVOLTAGE_SUM = 0x0d

    INA3221_CONFIG_RST      = (1<<15)
    INA3221_CONFIG_CH1_EN   = (1<<14)
    INA3221_CONFIG_CH2_EN   = (1<<13)
    INA3221_CONFIG_CH3_EN   = (1<<12)
    INA3221_CONFIG_AVG2     = (1<<11)
    INA3221_CONFIG_AVG1     = (1<<10)
    INA3221_CONFIG_AVG0     = (1<< 9)
    INA3221_CONFIG_VBUS_CT2 = (1<< 8)
    INA3221_CONFIG_VBUS_CT1 = (1<< 7)
    INA3221_CONFIG_VBUS_CT0 = (1<< 6)
    INA3221_CONFIG_VSH_CT2  = (1<< 5)
    INA3221_CONFIG_VSH_CT1  = (1<< 4)
    INA3221_CONFIG_VSH_CT0  = (1<< 3)
    INA3221_CONFIG_MODE_2   = (1<< 2)
    INA3221_CONFIG_MODE_1   = (1<< 1)
    INA3221_CONFIG_MODE_0   = (1<< 0)

    _VOLTAGE_LUT = { 'bus':   {'reg_base': INA3221_REG_BUSVOLTAGE_1,   'convert': lambda x: x/1000}, 
                     'shunt': {'reg_base': INA3221_REG_SHUNTVOLTAGE_1, 'convert': lambda x: x/1000/2/10} }
    
    SHUNT_RESISTOR_DEFAULT = 0.1

    def __init__(self, twi=1, addr=INA3221_ADDRESS, shunt_resistor=SHUNT_RESISTOR_DEFAULT):
        self._bus = smbus.SMBus(twi)
        self._addr = addr
        self._shunt_resistor = shunt_resistor

        # Always reset
        self._write_register(self.INA3221_REG_CONFIG, self.INA3221_CONFIG_RST)
        while self._read_register(self.INA3221_REG_CONFIG) & self.INA3221_CONFIG_RST: time.sleep(0)
        
        config = self.INA3221_CONFIG_CH1_EN | \
                 self.INA3221_CONFIG_CH2_EN | \
                 self.INA3221_CONFIG_CH3_EN | \
                 self.INA3221_CONFIG_AVG2 | \
                 self.INA3221_CONFIG_AVG1 | \
                 self.INA3221_CONFIG_AVG0 | \
                 self.INA3221_CONFIG_VBUS_CT2 | \
                 self.INA3221_CONFIG_VBUS_CT1 | \
                 self.INA3221_CONFIG_VBUS_CT0 | \
                 self.INA3221_CONFIG_VSH_CT2 | \
                 self.INA3221_CONFIG_MODE_2 | \
                 self.INA3221_CONFIG_MODE_1 | \
                 self.INA3221_CONFIG_MODE_0

        self._write_register(self.INA3221_REG_CONFIG, config)

        # Spin upto ~10ms first conversion is complete for all channels, no
        # other way to tell config is complete.  Prevents the first reading
        # from returning all zeros.
        timeout = 10
        while not all((self.get_voltage(i) and self.get_current(i)) for i in range(3)) and timeout > 0:
            time.sleep(0.001)
            timeout -= 1

    def _read_register(self, reg):
        data = self._bus.read_word_data(self._addr, reg).to_bytes(2, byteorder='big')
        return struct.unpack('H', data)[0]

    def _write_register(self, reg, data):
        swap = int.from_bytes(struct.pack('H', data), byteorder='big')
        return self._bus.write_word_data(self._addr, reg, swap)

    def get_voltage(self, ch, reg_type = 'bus'):
        """Get voltage for given channel in volts"""
        if ch < 0 or ch > 2:
            raise ValueError('Invalid channel')
        lut = self._VOLTAGE_LUT[reg_type]
        reg = lut['reg_base'] + ch * 2
        value = self._read_register(reg)
        value = (value - 65536) if value > 32767 else value
        return lut['convert'](value)
    
    def get_current(self, ch):
        return self.get_voltage(ch, 'shunt') / self._shunt_resistor * 100


class SolarPower():
    """Solar power monitor to monitor a SY-M150-14.6 + LiFePo4 battery + 25W solar panel"""
    _CH_LUT = {
            'solar':   {'ch': 0, 'gain': -1},
            'battery': {'ch': 1, 'gain': -1},
            'output':  {'ch': 2, 'gain':  1}
            }

    def __init__(self, scheduler, period=1, mean_period_cnt=30):
        self._sample_period = period
        self._mean_period_cnt = mean_period_cnt
        self._scheduler = scheduler
        self._ina3221 = INA3221()
        self._samples = []

        with open('/etc/machine-id') as fp:
            self._machine_id = fp.read().strip()

    def _read_channel(self, ch_dict):
        ch = ch_dict['ch']
        gain = ch_dict['gain']
        d = { 'v_load':  self._ina3221.get_voltage(ch, 'bus'),
              'current': self._ina3221.get_current(ch) / 1000 * gain
            }
        # Not sure how this is useful:
        #'v_shunt': self._ina3221.get_voltage(ch, 'shunt')
        return d

    def _sample_cb(self):
        d = { k: self._read_channel(v) for k, v in self._CH_LUT.items() }
        d['@machine_id'] = self._machine_id
        d['@time'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

        #print(json.dumps(d))
        #print(json.dumps({'sample': d['@time']}))

        self._next_sample += self._sample_period
        s.enterabs(self._next_sample, 1, self._sample_cb)

        self._samples += [d]
        if len(self._samples) >= self._mean_period_cnt:
            s.enter(0, 0, self._calc_mean_cb)

    def _get_ch_means(self, name):
        cnt = len(self._samples)
        field_names = self._samples[0][name].keys()
        # Function to yield every sample from a given field
        field_gen = lambda field: (sample[name][field] for sample in self._samples)
        # Return dictionary with the mean of each field
        return { f: sum(field_gen(f))/cnt for f in field_names}


    def _calc_mean_cb(self):
        d = { '@machine_id': self._machine_id,
              '@time': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds') }

        names = tuple(filter(lambda x: not x.startswith('@'), self._samples[0].keys()))
        d.update({n: self._get_ch_means(n) for n in names})

        print(json.dumps(d))
        self._samples.clear()

    def start(self):
        self._next_sample = time.monotonic()
        self._sample_cb()


if __name__ == '__main__':

    s = sched.scheduler()

    sp = SolarPower(s, mean_period_cnt=30)
    sp.start()

    s.run()
