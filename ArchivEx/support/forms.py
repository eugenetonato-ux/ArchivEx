from django import forms
from .models import SupportRequest, SupportReply


class SupportRequestForm(forms.ModelForm):
    """Formulaire de soumission d'une demande de support étudiant ou invité."""

    guest_name = forms.CharField(
        required=False,
        label="Votre nom complet",
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#2563EB]",
            "placeholder": "Ex: Jean Dupont",
            "id": "support-guest-name",
        }),
    )
    guest_email = forms.EmailField(
        required=False,
        label="Votre adresse email",
        widget=forms.EmailInput(attrs={
            "class": "w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#2563EB]",
            "placeholder": "Ex: jean.dupont@gmail.com",
            "id": "support-guest-email",
        }),
    )
    category = forms.ChoiceField(
        choices=SupportRequest.CATEGORY_CHOICES,
        label="Motif / Objet",
        widget=forms.Select(attrs={
            "class": "w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#2563EB]",
            "id": "support-category",
        }),
    )
    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={
            "class": "w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#2563EB] resize-none",
            "rows": 6,
            "placeholder": "Décrivez votre problème ou votre question en détail...",
            "id": "support-message",
        }),
    )

    class Meta:
        model = SupportRequest
        fields = ["guest_name", "guest_email", "category", "message"]

    def __init__(self, *args, is_authenticated=True, **kwargs):
        super().__init__(*args, **kwargs)
        if is_authenticated:
            self.fields["guest_name"].required = False
            self.fields["guest_email"].required = False
        else:
            self.fields["guest_name"].required = True
            self.fields["guest_email"].required = True


class SupportReplyForm(forms.ModelForm):
    """Formulaire de réponse administrateur à une demande de support."""

    message = forms.CharField(
        label="Réponse",
        widget=forms.Textarea(attrs={
            "class": "w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#2563EB] resize-none",
            "rows": 5,
            "placeholder": "Rédigez votre réponse à l'étudiant...",
            "id": "admin-reply-message",
        }),
    )

    class Meta:
        model = SupportReply
        fields = ["message"]
