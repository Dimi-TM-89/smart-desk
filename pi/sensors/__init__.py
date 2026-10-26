"""Sensor classes: one small class per sensor.

    ultrasonic.Ultrasonic        HC-SR04 presence at the entrance (digital)
    light.LightSensor            BH1750 desk light (I2C)
    temperature.TemperatureSensor BMP280 room temperature (I2C)
    adc.AnalogInputs             MCP3008: potentiometer + window LDR (SPI)
    button.Button                fan button + shade up/down buttons (digital, pull-up)
"""
