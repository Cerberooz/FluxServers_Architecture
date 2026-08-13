"""Outbound integrations: game panel, email, payment providers.

One name per thing. The panel client previously carried four aliases
(Pelican/Pterodactyl/Fluid/Hanodactyl) across three modules, which is the
naming sprawl the architecture review flagged as M-2. FluidPanel is the only
panel this application talks to, so it is the only name here.
"""

from fluxweb.integrations.fluid import FluidPanelClient, get_fluid_client
from fluxweb.integrations.mailer import get_mailer

__all__ = ["FluidPanelClient", "get_fluid_client", "get_mailer"]
