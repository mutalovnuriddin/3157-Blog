from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from .models import Profile, Post, Comment


class ProfileuserCreateForm(UserCreationForm):
    class Meta:
        model = Profile
        fields = ['username', 'email', 'phone_number', 'bio', 'avatar']


class ProfileLoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['username', 'phone_number', 'bio', 'avatar']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
        }


class PostCreateForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title', 'desc', 'img', 'video']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sarlavha kiriting'}),
            'desc': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Izoh kiriting'}),
            'img': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'video': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'video/*'}),
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['text']
        widgets = {
            'text': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Fikringizni yozing...',
                'aria-label': 'Izoh matni',
            }),
        }

    def clean_text(self):
        text = self.cleaned_data['text'].strip()
        if not text:
            raise forms.ValidationError('Izoh matni bo‘sh bo‘lmasligi kerak.')
        return text