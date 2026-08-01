from aegis.core.messages import SensorMessage


class FusionEngine:

    def __init__(self):
        self.measurements = []


    def add_measurement(
        self,
        message: SensorMessage,
        weight: float = 1.0
    ):

        self.measurements.append(
            {
                "message": message,
                "weight": weight
            }
        )


    def fuse(self):

        if not self.measurements:
            return None


        weighted_sum = 0
        total_weight = 0


        for item in self.measurements:

            value = item["message"].data["value"]
            weight = item["weight"]

            weighted_sum += value * weight
            total_weight += weight


        estimate = weighted_sum / total_weight


        return {
            "fused_value": estimate,
            "confidence": total_weight,
            "sensor_count": len(self.measurements)
        }
