# Support for common SPI based thermocouple and RTD temperature sensors
#
# Copyright (C) 2018  Petri Honkala <cruwaller@gmail.com>
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math


######################################################################
# SensorBase
######################################################################

REPORT_TIME = 0.300

VALID_SPI_SENSORS = {
    'MAX31855' : 1,
    'MAX31856' : 2,
    'MAX31865' : 4,
    'MAX6675'  : 8
}

class error(Exception):
    pass

class SensorBase:
    error = error
    def __init__(self, config):
        self._callback = None
        self.min_sample_value = self.max_sample_value = 0
        self._report_clock = 0
        ppins = config.get_printer().lookup_object('pins')
        sensor_pin = config.get('sensor_pin')
        pin_params = ppins.lookup_pin('digital_out', sensor_pin)
        self.mcu = mcu = pin_params['chip']
        pin = pin_params['pin']
        # SPI bus configuration
        spi_oid = mcu.create_oid()
        spi_mode = config.getint('spi_mode', minval=0, maxval=3)
        spi_speed = config.getint('spi_speed', minval=0)
        mcu.add_config_cmd(
            "config_spi oid=%u bus=%u pin=%s"
            " mode=%u rate=%u shutdown_msg=" % (
                spi_oid, 0, pin, spi_mode, spi_speed))
        config_cmd = "".join("%02x" % b for b in self.get_configs())
        mcu.add_config_cmd("spi_send oid=%u data=%s" % (
            spi_oid, config_cmd), is_init=True)
        # Reader chip configuration
        self.oid = oid = mcu.create_oid()
        mcu.add_config_cmd(
            "config_thermocouple oid=%u spi_oid=%u chip_type=%u" % (
                oid, spi_oid, VALID_SPI_SENSORS[self.chip_type]))
        mcu.register_msg(self._handle_spi_response,
            "thermocouple_result", oid)
        mcu.add_config_object(self)
    def setup_minmax(self, min_temp, max_temp):
        adc_range = [self.calc_adc(min_temp), self.calc_adc(max_temp)]
        self.min_sample_value = min(adc_range)
        self.max_sample_value = max(adc_range)
    def setup_callback(self, cb):
        self._callback = cb
    def get_report_time_delta(self):
        return REPORT_TIME
    def build_config(self):
        clock = self.mcu.get_query_slot(self.oid)
        self._report_clock = self.mcu.seconds_to_clock(REPORT_TIME)
        self.mcu.add_config_cmd(
            "query_thermocouple oid=%u clock=%u rest_ticks=%u"
            " min_value=%u max_value=%u" % (
                self.oid, clock, self._report_clock,
                self.min_sample_value, self.max_sample_value))
    def _handle_spi_response(self, params):
        last_value      = params['value']
        next_clock      = self.mcu.clock32_to_clock64(params['next_clock'])
        last_read_clock = next_clock - self._report_clock
        last_read_time  = self.mcu.clock_to_print_time(last_read_clock)
        temp = self.calc_temp(last_value)
        self.check_faults(params['fault'])
        if self._callback is not None:
            self._callback(last_read_time, temp)


######################################################################
# MAX31856 thermocouple
######################################################################

MAX31856_CR0_REG           = 0x00
MAX31856_CR0_AUTOCONVERT   = 0x80
MAX31856_CR0_1SHOT         = 0x40
MAX31856_CR0_OCFAULT1      = 0x20
MAX31856_CR0_OCFAULT0      = 0x10
MAX31856_CR0_CJ            = 0x08
MAX31856_CR0_FAULT         = 0x04
MAX31856_CR0_FAULTCLR      = 0x02
MAX31856_CR0_FILT50HZ      = 0x01
MAX31856_CR0_FILT60HZ      = 0x00

MAX31856_CR1_REG           = 0x01
MAX31856_CR1_AVGSEL1       = 0x00
MAX31856_CR1_AVGSEL2       = 0x10
MAX31856_CR1_AVGSEL4       = 0x20
MAX31856_CR1_AVGSEL8       = 0x30
MAX31856_CR1_AVGSEL16      = 0x70

MAX31856_MASK_REG                          = 0x02
MAX31856_MASK_COLD_JUNCTION_HIGH_FAULT     = 0x20
MAX31856_MASK_COLD_JUNCTION_LOW_FAULT      = 0x10
MAX31856_MASK_THERMOCOUPLE_HIGH_FAULT      = 0x08
MAX31856_MASK_THERMOCOUPLE_LOW_FAULT       = 0x04
MAX31856_MASK_VOLTAGE_UNDER_OVER_FAULT     = 0x02
MAX31856_MASK_THERMOCOUPLE_OPEN_FAULT      = 0x01

MAX31856_CJHF_REG          = 0x03
MAX31856_CJLF_REG          = 0x04
MAX31856_LTHFTH_REG        = 0x05
MAX31856_LTHFTL_REG        = 0x06
MAX31856_LTLFTH_REG        = 0x07
MAX31856_LTLFTL_REG        = 0x08
MAX31856_CJTO_REG          = 0x09
MAX31856_CJTH_REG          = 0x0A
MAX31856_CJTL_REG          = 0x0B
MAX31856_LTCBH_REG         = 0x0C
MAX31856_LTCBM_REG         = 0x0D
MAX31856_LTCBL_REG         = 0x0E

MAX31856_SR_REG            = 0x0F
MAX31856_FAULT_CJRANGE     = 0x80  # Cold Junction out of range
MAX31856_FAULT_TCRANGE     = 0x40  # Thermocouple out of range
MAX31856_FAULT_CJHIGH      = 0x20  # Cold Junction High
MAX31856_FAULT_CJLOW       = 0x10  # Cold Junction Low
MAX31856_FAULT_TCHIGH      = 0x08  # Thermocouple Low
MAX31856_FAULT_TCLOW       = 0x04  # Thermocouple Low
MAX31856_FAULT_OVUV        = 0x02  # Under Over Voltage
MAX31856_FAULT_OPEN        = 0x01

MAX31856_SCALE = 5
MAX31856_MULT = 0.0078125

class MAX31856(SensorBase):
    def __init__(self, config):
        self.chip_type = "MAX31856"
        types = {
            "B" : 0b0000,
            "E" : 0b0001,
            "J" : 0b0010,
            "K" : 0b0011,
            "N" : 0b0100,
            "R" : 0b0101,
            "S" : 0b0110,
            "T" : 0b0111,
        }
        self.tc_type = config.getchoice('tc_type', types, default="K")
        self.use_50Hz_filter = config.getboolean('tc_use_50Hz_filter', False)
        averages = {
            "1"  : MAX31856_CR1_AVGSEL1,
            "2"  : MAX31856_CR1_AVGSEL2,
            "4"  : MAX31856_CR1_AVGSEL4,
            "8"  : MAX31856_CR1_AVGSEL8,
            "16" : MAX31856_CR1_AVGSEL16
        }
        self.average_count = config.getchoice('tc_averaging_count', averages, "1")
        SensorBase.__init__(self, config)
    def check_faults(self, fault):
        if fault & MAX31856_FAULT_CJRANGE:
            raise self.error("Max31856: Cold Junction Range Fault")
        if fault & MAX31856_FAULT_TCRANGE:
            raise self.error("Max31856: Thermocouple Range Fault")
        if fault & MAX31856_FAULT_CJHIGH:
            raise self.error("Max31856: Cold Junction High Fault")
        if fault & MAX31856_FAULT_CJLOW:
            raise self.error("Max31856: Cold Junction Low Fault")
        if fault & MAX31856_FAULT_TCHIGH:
            raise self.error("Max31856: Thermocouple High Fault")
        if fault & MAX31856_FAULT_TCLOW:
            raise self.error("Max31856: Thermocouple Low Fault")
        if fault & MAX31856_FAULT_OVUV:
            raise self.error("Max31856: Over/Under Voltage Fault")
        if fault & MAX31856_FAULT_OPEN:
            raise self.error("Max31856: Thermocouple Open Fault")
    def calc_temp(self, adc):
        adc = adc >> MAX31856_SCALE
        # Fix sign bit:
        if adc & 0x40000:
            adc = ((adc & 0x3FFFF) + 1) * -1
        temp = MAX31856_MULT * adc
        return temp
    def calc_adc(self, temp):
        adc = int( ( temp / MAX31856_MULT ) + 0.5 ) # convert to ADC value
        adc = adc << MAX31856_SCALE
        return adc
    def get_configs(self):
        cmds = []
        value = MAX31856_CR0_AUTOCONVERT
        if self.use_50Hz_filter:
            value |= MAX31856_CR0_FILT50HZ
        cmds.append(0x80 + MAX31856_CR0_REG)
        cmds.append(value)

        value  = self.tc_type
        value |= self.average_count
        cmds.append(0x80 + MAX31856_CR1_REG)
        cmds.append(value)

        value = (MAX31856_MASK_VOLTAGE_UNDER_OVER_FAULT |
                 MAX31856_MASK_THERMOCOUPLE_OPEN_FAULT)
        cmds.append(0x80 + MAX31856_MASK_REG)
        cmds.append(value)
        return cmds


######################################################################
# MAX31855 thermocouple
######################################################################

MAX31855_SCALE = 18
MAX31855_MULT = 0.25

class MAX31855(SensorBase):
    def __init__(self, config):
        self.chip_type = "MAX31855"
        SensorBase.__init__(self, config)
    def check_faults(self, fault):
        pass
    def calc_temp(self, adc):
        if adc & 0x1:
            raise self.error("MAX31855 : Open Circuit")
        if adc & 0x2:
            raise self.error("MAX31855 : Short to GND")
        if adc & 0x4:
            raise self.error("MAX31855 : Short to Vcc")
        adc = adc >> MAX31855_SCALE
        # Fix sign bit:
        if adc & 0x2000:
            adc = ((adc & 0x1FFF) + 1) * -1
        temp = MAX31855_MULT * adc
        return temp
    def calc_adc(self, temp):
        adc = int( ( temp / MAX31855_MULT ) + 0.5 ) # convert to ADC value
        adc = adc << MAX31855_SCALE
        return adc
    def get_configs(self):
        return []


######################################################################
# MAX6675 thermocouple
######################################################################

MAX6675_SCALE = 3
MAX6675_MULT = 0.25

class MAX6675(SensorBase):
    def __init__(self, config):
        self.chip_type = "MAX6675"
        SensorBase.__init__(self, config)
    def check_faults(self, fault):
        pass
    def calc_temp(self, adc):
        if adc & 0x02:
            raise self.error("Max6675 : Device ID error")
        if adc & 0x04:
            raise self.error("Max6675 : Thermocouple Open Fault")
        adc = adc >> MAX6675_SCALE
        # Fix sign bit:
        if adc & 0x2000:
            adc = ((adc & 0x1FFF) + 1) * -1
        temp = MAX6675_MULT * adc
        return temp
    def calc_adc(self, temp):
        adc = int( ( temp / MAX6675_MULT ) + 0.5 ) # convert to ADC value
        adc = adc << MAX6675_SCALE
        return adc
    def get_configs(self):
        return []


######################################################################
# MAX31865 (RTD sensor)
######################################################################

MAX31865_CONFIG_REG            = 0x00
MAX31865_RTDMSB_REG            = 0x01
MAX31865_RTDLSB_REG            = 0x02
MAX31865_HFAULTMSB_REG         = 0x03
MAX31865_HFAULTLSB_REG         = 0x04
MAX31865_LFAULTMSB_REG         = 0x05
MAX31865_LFAULTLSB_REG         = 0x06
MAX31865_FAULTSTAT_REG         = 0x07

MAX31865_CONFIG_BIAS           = 0x80
MAX31865_CONFIG_MODEAUTO       = 0x40
MAX31865_CONFIG_1SHOT          = 0x20
MAX31865_CONFIG_3WIRE          = 0x10
MAX31865_CONFIG_FAULTCLEAR     = 0x02
MAX31865_CONFIG_FILT50HZ       = 0x01

MAX31865_FAULT_HIGHTHRESH      = 0x80
MAX31865_FAULT_LOWTHRESH       = 0x40
MAX31865_FAULT_REFINLOW        = 0x20
MAX31865_FAULT_REFINHIGH       = 0x10
MAX31865_FAULT_RTDINLOW        = 0x08
MAX31865_FAULT_OVUV            = 0x04

VAL_A = 0.00390830
VAL_B = 0.0000005775
VAL_C = -0.00000000000418301
VAL_ADC_MAX = 32768.0 # 2^15

class MAX31865(SensorBase):
    def __init__(self, config):
        self.chip_type = "MAX31865"
        self.rtd_nominal_r = config.getint('rtd_nominal_r', 100)
        self.reference_r = config.getfloat('rtd_reference_r', 430., above=0.)
        self.num_wires  = config.getint('rtd_num_of_wires', 2)
        self.use_50Hz_filter = config.getboolean('rtd_use_50Hz_filter', False)
        SensorBase.__init__(self, config)
    def check_faults(self, fault):
        if fault & 0x80:
            raise self.error("Max31865 RTD input is disconnected")
        if fault & 0x40:
            raise self.error("Max31865 RTD input is shorted")
        if fault & 0x20:
            raise self.error("Max31865 VREF- is greater than 0.85 * VBIAS, FORCE- open")
        if fault & 0x10:
            raise self.error("Max31865 VREF- is less than 0.85 * VBIAS, FORCE- open")
        if fault & 0x08:
            raise self.error("Max31865 VRTD- is less than 0.85 * VBIAS, FORCE- open")
        if fault & 0x04:
            raise self.error("Max31865 Overvoltage or undervoltage fault")
        if fault & 0x03:
            raise self.error("Max31865 Unspecified error")
    def calc_temp(self, adc):
        adc = adc >> 1 # remove fault bit
        R_rtd = (self.reference_r * adc) / VAL_ADC_MAX
        temp = (
            (( ( -1 * self.rtd_nominal_r ) * VAL_A ) +
             math.sqrt( ( self.rtd_nominal_r * self.rtd_nominal_r * VAL_A * VAL_A ) -
                        ( 4 * self.rtd_nominal_r * VAL_B * ( self.rtd_nominal_r - R_rtd ) )))
            / (2 * self.rtd_nominal_r * VAL_B))
        return temp
    def calc_adc(self, temp):
        R_rtd = temp * ( 2 * self.rtd_nominal_r * VAL_B )
        R_rtd = math.pow( ( R_rtd + ( self.rtd_nominal_r * VAL_A ) ), 2)
        R_rtd = -1 * ( R_rtd - ( self.rtd_nominal_r * self.rtd_nominal_r * VAL_A * VAL_A ) )
        R_rtd = R_rtd / ( 4 * self.rtd_nominal_r * VAL_B )
        R_rtd = ( -1 * R_rtd ) + self.rtd_nominal_r
        adc = int( ( ( R_rtd * VAL_ADC_MAX ) / self.reference_r) + 0.5 )
        adc = adc << 1 # Add fault bit
        return adc
    def get_configs(self):
        value = (MAX31865_CONFIG_BIAS |
                 MAX31865_CONFIG_MODEAUTO |
                 MAX31865_CONFIG_FAULTCLEAR)
        if self.use_50Hz_filter:
            value |= MAX31865_CONFIG_FILT50HZ
        if self.num_wires == 3:
            value |= MAX31865_CONFIG_3WIRE
        cmd = 0x80 + MAX31865_CONFIG_REG
        return [cmd, value]


######################################################################
# Sensor registration
######################################################################

Sensors = {
    "MAX6675": MAX6675,
    "MAX31855": MAX31855,
    "MAX31856": MAX31856,
    "MAX31865": MAX31865,
}

def load_config(config):
    # Register sensors
    pheater = config.get_printer().lookup_object("heater")
    for name, klass in Sensors.items():
        pheater.add_sensor(name, klass)