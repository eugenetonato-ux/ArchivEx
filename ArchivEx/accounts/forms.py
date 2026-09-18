from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from academics.models import School, Level, Filiere
from .models import StudentProfile

User = get_user_model()


class StudentRegistrationForm(forms.ModelForm):
    first_name = forms.CharField(max_length=50, required=True, label="Prénom", widget=forms.TextInput(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
        'placeholder': 'Sophia'
    }))
    last_name = forms.CharField(max_length=50, required=True, label="Nom", widget=forms.TextInput(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
        'placeholder': 'Lokossou'
    }))
    email = forms.EmailField(required=True, label="Adresse Email", widget=forms.EmailInput(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
        'placeholder': 'sophialokossou@gmail.com'
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
        'placeholder': 'Tapez un mot de passe'
    }), label="Mot de passe")

    school = forms.ModelChoiceField(queryset=School.objects.filter(is_active=True), label="École / Université", widget=forms.Select(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))
    level = forms.ModelChoiceField(queryset=Level.objects.all(), label="Niveau d'étude", widget=forms.Select(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))
    filiere = forms.ModelChoiceField(queryset=Filiere.objects.all(), label="Filière", widget=forms.Select(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'password']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte avec cette adresse email existe déjà.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            StudentProfile.objects.create(
                user=user,
                school=self.cleaned_data['school'],
                level=self.cleaned_data['level'],
                filiere=self.cleaned_data['filiere'],
            )
        return user


class StudentLoginForm(AuthenticationForm):
    username = forms.CharField(label="Adresse Email ou identifiant", widget=forms.TextInput(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
        'placeholder': 'etudiant@gmail.com'
    }))
    password = forms.CharField(label="Mot de passe", widget=forms.PasswordInput(attrs={
        'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
        'placeholder': '••••••••'
    }))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_not_found = False
        self.password_incorrect = False
        self.tried_identifier = ""

    def clean(self):
        username = self.cleaned_data.get("username", "").strip()
        password = self.cleaned_data.get("password", "")
        self.tried_identifier = username

        if username and password:
            from django.db.models import Q
            from django.contrib.auth import authenticate
            # Vérification de l'existence du compte dans la base de données
            user_obj = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()

            if not user_obj:
                self.account_not_found = True
                raise forms.ValidationError(
                    "Identifiant non reconnu par la base de données. Vous n'avez pas encore de compte ?",
                    code="account_not_found",
                )

            # Le compte existe : tentative d'authentification avec son nom d'utilisateur officiel
            self.user_cache = authenticate(self.request, username=user_obj.username, password=password)

            if self.user_cache is None:
                self.password_incorrect = True
                raise forms.ValidationError(
                    "Votre identifiant est reconnu, mais le mot de passe saisi est incorrect.",
                    code="password_incorrect",
                )
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class StudentProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=50, required=False, label="Prénom", widget=forms.TextInput(attrs={
        'class': 'w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))
    last_name = forms.CharField(max_length=50, required=False, label="Nom", widget=forms.TextInput(attrs={
        'class': 'w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))

    school = forms.ModelChoiceField(queryset=School.objects.filter(is_active=True), label="École / Université", widget=forms.Select(attrs={
        'class': 'w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))
    level = forms.ModelChoiceField(queryset=Level.objects.all(), label="Niveau", widget=forms.Select(attrs={
        'class': 'w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))
    filiere = forms.ModelChoiceField(queryset=Filiere.objects.all(), label="Filière", widget=forms.Select(attrs={
        'class': 'w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] focus:outline-none focus:ring-2 focus:ring-[#2563EB]'
    }))

    class Meta:
        model = StudentProfile
        fields = ['school', 'level', 'filiere', 'avatar']
        widgets = {
            'avatar': forms.FileInput(attrs={'class': 'w-full text-xs text-slate-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-blue-50 file:text-[#2563EB] hover:file:bg-blue-100'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, 'user') and self.instance.user_id:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name

    def save(self, commit=True):
        profile = super().save(commit=commit)
        user = getattr(profile, 'user', None)
        if user:
            first_name = self.cleaned_data.get('first_name')
            last_name = self.cleaned_data.get('last_name')
            if first_name is not None:
                user.first_name = first_name
            if last_name is not None:
                user.last_name = last_name
            user.save()
        return profile


class ForcePasswordChangeForm(SetPasswordForm):
    """Formulaire forçant l'étudiant à définir son nouveau mot de passe personnel."""

    new_password1 = forms.CharField(
        label="Nouveau mot de passe personnel",
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
            'placeholder': 'Définissez votre nouveau mot de passe',
            'autocomplete': 'new-password',
            'id': 'id_new_password1',
        }),
        help_text="Votre mot de passe doit comporter au moins 8 caractères."
    )
    new_password2 = forms.CharField(
        label="Confirmez le nouveau mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-[#071A49] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]',
            'placeholder': 'Confirmez votre nouveau mot de passe',
            'autocomplete': 'new-password',
            'id': 'id_new_password2',
        }),
    )