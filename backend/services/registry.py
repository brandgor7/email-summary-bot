from services.sources.base import EmailSource
from services.destinations.base import DigestDestination

from services.sources.outlook import OutlookSource
# from services.destinations.telegram import TelegramDestination  # registered in Phase 4

SOURCE_PROVIDERS: dict[str, EmailSource] = {
    "outlook": OutlookSource(),
}

DESTINATION_PROVIDERS: dict[str, DigestDestination] = {}
