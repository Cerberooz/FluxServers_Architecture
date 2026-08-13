<?php

namespace Pterodactyl\Http\Requests\Auth;

use Pterodactyl\Rules\Username;
use Illuminate\Foundation\Http\FormRequest;

class RegisterRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'email' => 'required|email:strict|between:1,191|unique:users,email',
            'username' => ['required', 'between:1,191', 'unique:users,username', new Username()],
            'name_first' => 'required|string|between:1,191',
            'name_last' => 'required|string|between:1,191',
            'password' => 'required|string|confirmed|min:8',
        ];
    }
}
