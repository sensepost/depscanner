import logging
from discord_webhook import DiscordWebhook, DiscordEmbed


class DiscordBell:
    def __init__(self, webhook_url: str, logger: logging.Logger):
        self.webhook_url = webhook_url
        self.logger = logger

    def ping(self, msg: str, title="📦💥 Orphan dependency detected 💥📦"):
        if self.webhook_url is not None and len(self.webhook_url)>0:
            webhook = DiscordWebhook(url=self.webhook_url)
            embed = DiscordEmbed(title=title, color="03b2f8")
            embed.set_description(msg)
            webhook.add_embed(embed)
            response = webhook.execute()
        #     self.logger.info("Discord response: %s", response)
        # else:
        #     self.logger.debug("No discord webhook defined. Skipping notification")
