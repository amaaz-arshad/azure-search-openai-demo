import asyncio
import logging

import aiohttp

logger = logging.getLogger("scripts")

HUBSPOT_CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
HUBSPOT_REQUEST_TIMEOUT_SECONDS = 10
# Custom HubSpot property that marks a contact as having registered through the Free Bot.
HUBSPOT_FREE_BOT_PROPERTY = "neriliofreebot"
# How much of a HubSpot error body reaches the log. Enough to carry the API's own message
# (including the "Existing ID" a 409 reports) without dumping an unbounded payload.
HUBSPOT_LOGGED_BODY_LIMIT = 500


class HubSpotContactStore:
    """Creates a HubSpot CRM contact for a freshly verified Free Bot account.

    Every failure is swallowed and logged rather than raised. The contact is created *after* the
    account blob is written, so an exception escaping this class would hand the user an error for
    an account that already exists — and Free Bot emails cannot be re-registered, so they could
    never retry. A CRM outage, a revoked token or a renamed property therefore costs a log line,
    not a signup.

    Unconfigured (no HUBSPOT_API_KEY) is a normal state, not an error: local runs and test
    deployments simply do not sync to the CRM.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        contacts_url: str = HUBSPOT_CONTACTS_URL,
        timeout_seconds: int = HUBSPOT_REQUEST_TIMEOUT_SECONDS,
    ):
        self.api_key = (api_key or "").strip()
        self.contacts_url = contacts_url
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def build_contact_properties(
        *,
        email: str,
        first_name: str = "",
        last_name: str = "",
        company: str = "",
    ) -> dict[str, str]:
        """The HubSpot ``properties`` object for a Free Bot registration.

        Blank values are omitted instead of sent as empty strings, so a field that HubSpot already
        holds for an address is never blanked out by a signup that did not collect it.
        """
        properties = {
            "email": email.strip().lower(),
            HUBSPOT_FREE_BOT_PROPERTY: "true",
        }
        for property_name, raw_value in (
            ("firstname", first_name),
            ("lastname", last_name),
            ("company", company),
        ):
            value = (raw_value or "").strip()
            if value:
                properties[property_name] = value
        return properties

    @staticmethod
    def interpret_contact_response(*, email: str, status_code: int, body: str) -> bool:
        """Log the outcome of a create-contact call and report whether a contact was created."""
        if 200 <= status_code < 300:
            logger.info("Created HubSpot contact for %s", email)
            return True

        if status_code == 409:
            # HubSpot rejects a duplicate email with 409. Free Bot signup already refuses an
            # address it knows, so reaching this means the contact predates the bot (imported, or
            # captured by another form). Left untouched on purpose: a signup is not the authority
            # on a contact that already exists, and overwriting could clobber sales-owned fields.
            logger.info(
                "HubSpot already has a contact for %s; leaving it unchanged: %s",
                email,
                body[:HUBSPOT_LOGGED_BODY_LIMIT],
            )
            return False

        logger.error(
            "Creating a HubSpot contact for %s failed with status %s: %s",
            email,
            status_code,
            body[:HUBSPOT_LOGGED_BODY_LIMIT],
        )
        return False

    async def create_contact(
        self,
        *,
        email: str,
        first_name: str = "",
        last_name: str = "",
        company: str = "",
    ) -> bool:
        """Create the contact. Returns True only when HubSpot confirms a new contact."""
        if not self.is_configured():
            logger.info("HUBSPOT_API_KEY is not set, so no HubSpot contact was created for %s", email)
            return False

        properties = self.build_contact_properties(
            email=email,
            first_name=first_name,
            last_name=last_name,
            company=company,
        )

        try:
            async with aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            ) as session:
                async with session.post(self.contacts_url, json={"properties": properties}) as response:
                    body = await response.text()
                    return self.interpret_contact_response(email=email, status_code=response.status, body=body)
        # aiohttp signals a blown total timeout with the builtin TimeoutError on Python 3.11+ and
        # asyncio.TimeoutError on older runtimes; both are named so the log stays specific.
        except (TimeoutError, asyncio.TimeoutError):
            logger.error(
                "Creating a HubSpot contact for %s timed out after %ss",
                email,
                self.timeout_seconds,
            )
            return False
        except Exception:
            logger.exception("Creating a HubSpot contact for %s failed", email)
            return False
