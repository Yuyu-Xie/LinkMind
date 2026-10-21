from django import forms


class BookmarkForm(forms.Form):
    url = forms.URLField(max_length=2048, label="URL")
    title = forms.CharField(max_length=512, required=False, label="标题")
    description = forms.CharField(
        required=False, label="描述", widget=forms.Textarea(attrs={"rows": 2})
    )
    notes = forms.CharField(
        required=False, label="笔记", widget=forms.Textarea(attrs={"rows": 2})
    )
    tag_names = forms.CharField(required=False, label="标签，逗号分隔")
    unread = forms.BooleanField(required=False, label="未读")
