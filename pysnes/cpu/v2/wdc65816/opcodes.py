

class WDC65816Opcodes:
    def AND8(self, data):
        self.A = (self.A & 0xFF00) | (self.A & 0xFF & data & 0xFF)
        self.ZF = self.A & 0xFF == 0
        self.NF = bool(self.A & 0x80)
        return self.A & 0xFF

    def AND16(self, data):
        self.A = self.A & data
        self.ZF = self.A & 0xFFFF == 0
        self.NF = bool(self.A & 0x8000)
        return self.A
