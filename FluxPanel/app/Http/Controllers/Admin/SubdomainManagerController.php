<?php

namespace Pterodactyl\Http\Controllers\Admin;

use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Crypt;
use Pterodactyl\Http\Controllers\Controller;
use Pterodactyl\Models\ServerSubdomain;
use Pterodactyl\Models\SubdomainDnsOperation;
use Pterodactyl\Models\SubdomainDomain;
use Pterodactyl\Contracts\Repository\SettingsRepositoryInterface;
use Pterodactyl\Services\Subdomains\DNSProvider;

class SubdomainManagerController extends Controller
{
    public function __construct(private SettingsRepositoryInterface $settings) {}

    public function index()
    {
        return view('admin.subdomains.index', ['domains' => SubdomainDomain::query()->orderBy('domain')->get(), 'subdomains' => ServerSubdomain::query()->with(['server', 'domain'])->latest()->paginate(25), 'operations' => SubdomainDnsOperation::query()->where('status', 'failed')->with('subdomain')->latest()->limit(25)->get(), 'configured' => (bool) $this->settings->get('subdomains:cloudflare:token')]);
    }

    public function saveSettings(Request $request): RedirectResponse
    {
        $data = $request->validate(['token' => 'nullable|string|min:20']);
        if (!empty($data['token'])) $this->settings->set('subdomains:cloudflare:token', Crypt::encryptString($data['token']));
        return redirect()->route('admin.subdomains')->with('success', 'Cloudflare settings saved.');
    }

    public function test(DNSProvider $provider): RedirectResponse
    {
        $provider->testConnection();
        return redirect()->route('admin.subdomains')->with('success', 'Cloudflare connection succeeded.');
    }

    public function storeDomain(Request $request): RedirectResponse
    {
        $data = $request->validate(['domain' => 'required|string|regex:/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/i|unique:subdomain_domains,domain', 'zone_id' => 'required|string|max:191', 'max_per_server' => 'required|integer|min:1|max:20', 'reserved_labels' => 'nullable|string', 'allowed_egg_ids' => 'nullable|string']);
        SubdomainDomain::query()->create(['domain' => strtolower($data['domain']), 'provider_zone_id' => $data['zone_id'], 'max_per_server' => $data['max_per_server'], 'reserved_labels' => array_values(array_filter(array_map('trim', explode(',', strtolower($data['reserved_labels'] ?? ''))))), 'allowed_egg_ids' => array_values(array_filter(array_map('intval', explode(',', $data['allowed_egg_ids'] ?? ''))))]);
        return redirect()->route('admin.subdomains')->with('success', 'Root domain added.');
    }

    public function toggleDomain(SubdomainDomain $domain): RedirectResponse { $domain->update(['enabled' => !$domain->enabled]); return back()->with('success', 'Domain updated.'); }
}
