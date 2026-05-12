from dataclasses import dataclass


@dataclass(frozen=True)
class SendResult:
    success: bool
    provider_message_id: str = ""
    response: str = ""


class BaseEmailProvider:
    def send(self, outbound_email):
        raise NotImplementedError
