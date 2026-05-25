from django import forms
from .models import Estrutura, Ordem, Rolagem, RolagemLeg

class RolagemForm(forms.ModelForm):
    class Meta:
        model = Rolagem
        fields = ['nome', 'filtro_liquidez']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Spread PETR4 Call Jun/Jul'}),
            'filtro_liquidez': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class RolagemLegForm(forms.ModelForm):
    ticker = forms.CharField(
        label="Ativo",
        widget=forms.TextInput(attrs={
            'class': 'form-control ticker-input', 
            'placeholder': 'Ticker', 
            'autocomplete': 'off'
        })
    )
    class Meta:
        model = RolagemLeg
        fields = ['quantidade']
        widgets = {
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Qtd (+ / -)'}),
        }

    def clean_ticker(self):
        ticker = self.cleaned_data.get('ticker').strip().upper()
        from core.models import AtivoB3
        ativo = AtivoB3.objects.filter(ticker=ticker).first()
        if not ativo:
            raise forms.ValidationError(f"Ativo '{ticker}' não encontrado.")
        return ativo

from django.forms import inlineformset_factory
RolagemLegFormSet = inlineformset_factory(
    Rolagem, RolagemLeg, 
    form=RolagemLegForm, 
    extra=4, 
    max_num=4, 
    can_delete=True
)

class EstruturaForm(forms.ModelForm):
    class Meta:
        model = Estrutura
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Carteira de Opções'}),
        }

class OrdemForm(forms.ModelForm):
    ativo_input = forms.CharField(
        label="Ativo",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Digite o ticker (ex: BOVAC180)', 
            'autocomplete': 'off'
        })
    )
    
    class Meta:
        model = Ordem
        fields = ['data', 'quantidade', 'preco']
        widgets = {
            'data': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'autocomplete': 'off'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantidade (+ Comprar / - Vender)', 'autocomplete': 'off'}),
            'preco': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Preço Unitário', 'step': '0.000001', 'autocomplete': 'off'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        ativo_input = cleaned_data.get('ativo_input')
        
        if ativo_input:
            ativo_input = ativo_input.strip().upper()
            from core.models import AtivoB3
            # Tenta encontrar o ativo exato pelo Ticker
            ativo = AtivoB3.objects.filter(ticker=ativo_input).first()
            if not ativo:
                self.add_error('ativo_input', f"Ativo '{ativo_input}' não encontrado no banco de dados.")
            else:
                cleaned_data['ativo'] = ativo
                
        return cleaned_data
        
    def save(self, commit=True):
        ordem = super().save(commit=False)
        ordem.ativo = self.cleaned_data.get('ativo')
        if commit:
            ordem.save()
        return ordem
