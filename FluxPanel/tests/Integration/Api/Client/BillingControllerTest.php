<?php

namespace Pterodactyl\Tests\Integration\Api\Client;

use Mockery;
use Pterodactyl\Models\User;
use Pterodactyl\Services\Billing\WebBillingService;

class BillingControllerTest extends ClientApiIntegrationTestCase
{
    public function testAuthenticatedUserCanReadTheirBillingSummary(): void
    {
        $user = User::factory()->create(['email' => 'customer@example.com']);
        $billing = Mockery::mock(WebBillingService::class);
        $billing->shouldReceive('forEmail')->once()->with($user->email)->andReturn([
            'services' => [['identifier' => 'abc123']],
            'invoices' => [['public_id' => 'invoice-1']],
            'summary' => ['monthly_total_cents' => 0],
        ]);
        $this->app->instance(WebBillingService::class, $billing);

        $this->actingAs($user)
            ->getJson('/api/client/billing')
            ->assertOk()
            ->assertJsonPath('services.0.identifier', 'abc123')
            ->assertJsonPath('invoices.0.public_id', 'invoice-1');
    }

    public function testBillingCannotBeReadWithoutAuthentication(): void
    {
        $this->getJson('/api/client/billing')->assertUnauthorized();
    }
}
