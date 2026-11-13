from pydantic import BaseModel, Field, field_validator


class OrderCreate(BaseModel):
    topic: str = Field(min_length=8, max_length=500)
    price_usd: float = Field(default=10.0, gt=0, le=10000)
    buyer_email: str | None = Field(default=None, max_length=320)

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 8:
            raise ValueError("Please provide a more specific research topic.")
        return value


class DemoRunRequest(BaseModel):
    topic: str = Field(
        default="How is the NEAR ecosystem developing autonomous business infrastructure?",
        min_length=8,
        max_length=500,
    )


class EmailCodeRequest(BaseModel):
    email: str = Field(min_length=6, max_length=320)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        import re

        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class VerifyEmailCodeRequest(EmailCodeRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class NearAuthVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=36, max_length=36)
    account_id: str = Field(min_length=2, max_length=64)
    public_key: str = Field(min_length=40, max_length=100)
    signature: str = Field(min_length=80, max_length=100)

    @field_validator("account_id")
    @classmethod
    def clean_account_id(cls, value: str) -> str:
        import re

        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{2,64}", value):
            raise ValueError("Enter a valid NEAR account ID.")
        return value
