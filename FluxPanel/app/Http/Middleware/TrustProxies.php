<?php

namespace Pterodactyl\Http\Middleware;

use Illuminate\Http\Request;
use Illuminate\Http\Middleware\TrustProxies as Middleware;

/**
 * Trust the host reverse proxy that terminates TLS for the panel container.
 *
 * The Apache container is published only on 127.0.0.1, so requests from the
 * public internet must pass through the host Nginx proxy first. Trusting its
 * forwarded headers ensures Laravel evaluates temporary signed links using
 * https://panel.fluxservers.cloud rather than the container's internal HTTP
 * address.
 */
class TrustProxies extends Middleware
{
    /**
     * The panel container is not directly publicly reachable.
     *
     * @var string
     */
    protected $proxies = '*';

    /**
     * Headers supplied by Nginx when it forwards public HTTPS traffic.
     *
     * @var int
     */
    protected $headers = Request::HEADER_X_FORWARDED_FOR
        | Request::HEADER_X_FORWARDED_HOST
        | Request::HEADER_X_FORWARDED_PORT
        | Request::HEADER_X_FORWARDED_PROTO
        | Request::HEADER_X_FORWARDED_PREFIX;
}
