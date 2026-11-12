from django import forms

from .models import Assignment, Availability, Role, User


class DateInput(forms.DateInput):
    input_type = "date"


class EmailLoginForm(forms.Form):
    email = forms.EmailField(label="Email address")


class AvailabilityRangeForm(forms.Form):
    STATE_CHOICES = Availability.STATES + [("clear", "Clear (remove)")]
    role = forms.ModelChoiceField(queryset=Role.objects.none(), widget=forms.HiddenInput)
    start = forms.DateField(widget=DateInput)
    end = forms.DateField(widget=DateInput)
    state = forms.ChoiceField(choices=STATE_CHOICES, initial=Availability.AVAILABLE)
    comment = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = roles if roles is not None else Role.objects.none()

    def clean(self):
        c = super().clean()
        if c.get("start") and c.get("end") and c["end"] < c["start"]:
            raise forms.ValidationError("End date is before start date.")
        if c.get("start") and c.get("end") and (c["end"] - c["start"]).days > 400:
            raise forms.ValidationError("Range too long (max ~13 months).")
        return c


class AssignRangeForm(forms.Form):
    FIRST_TWO = [("", "same as above"), (Assignment.FLAG_OVERLAP, "Overlap (incoming SLA)"),
                 (Assignment.FLAG_ONBOARDING, "Onboarding")]
    role = forms.ModelChoiceField(queryset=Role.objects.filter(self_service=True), widget=forms.HiddenInput)
    user = forms.ModelChoiceField(queryset=User.objects.none(), label="Person")
    start = forms.DateField(widget=DateInput)
    end = forms.DateField(widget=DateInput)
    flag = forms.ChoiceField(choices=Assignment.FLAGS, initial=Assignment.FLAG_NONE, label="Flag")
    first_two_flag = forms.ChoiceField(choices=FIRST_TWO, required=False, label="First 2 days")
    only_available = forms.BooleanField(required=False, label="Only days the person marked available")
    note = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, users=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = users if users is not None else User.objects.filter(is_active=True)
        self.fields["user"].label_from_instance = lambda u: f"{u.name} <{u.email}>"

    def clean(self):
        c = super().clean()
        if c.get("start") and c.get("end") and c["end"] < c["start"]:
            raise forms.ValidationError("End date is before start date.")
        return c


class UnassignRangeForm(forms.Form):
    role = forms.ModelChoiceField(queryset=Role.objects.all(), widget=forms.HiddenInput)
    user = forms.ModelChoiceField(queryset=User.objects.filter(is_active=True))
    start = forms.DateField(widget=DateInput)
    end = forms.DateField(widget=DateInput)


class CsvUploadForm(forms.Form):
    file = forms.FileField(label="CSV file")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 2 * 1024 * 1024:
            raise forms.ValidationError("File too large (max 2 MB).")
        try:
            return f.name, f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise forms.ValidationError("File must be UTF-8 CSV.")


class EligibilityAddForm(forms.Form):
    email = forms.EmailField()
    name = forms.CharField(max_length=200, required=False, help_text="Only used if the person is new")
    role = forms.ModelChoiceField(queryset=Role.objects.filter(self_service=True).select_related("phase"))
    eligible = forms.BooleanField(required=False, initial=True)
    confirmed_on = forms.DateField(required=False, widget=DateInput)
    note = forms.CharField(max_length=500, required=False)
