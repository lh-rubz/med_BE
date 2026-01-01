# أمثلة كود عملية

## 📱 Android (Kotlin)

### Google Sign-In مع جلب جميع البيانات

```kotlin
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.auth.api.signin.GoogleSignInAccount
import com.google.android.gms.auth.api.signin.GoogleSignInOptions
import com.google.api.client.googleapis.auth.oauth2.GoogleCredential
import com.google.api.client.http.javanet.NetHttpTransport
import com.google.api.client.json.jackson2.JacksonFactory
import okhttp3.*
import org.json.JSONObject

class GoogleAuthActivity : AppCompatActivity() {
    
    private val RC_SIGN_IN = 9001
    
    fun signInWithGoogle() {
        val gso = GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            .requestEmail()
            .requestProfile()
            .requestIdToken(getString(R.string.default_web_client_id))
            .requestServerAuthCode(getString(R.string.default_web_client_id))
            .build()
        
        val googleSignInClient = GoogleSignIn.getClient(this, gso)
        val signInIntent = googleSignInClient.signInIntent
        startActivityForResult(signInIntent, RC_SIGN_IN)
    }
    
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        
        if (requestCode == RC_SIGN_IN) {
            val task = GoogleSignIn.getSignedInAccountFromIntent(data)
            task.addOnSuccessListener { account ->
                // احصل على id_token
                val idToken = account.idToken
                
                // احصل على access_token (للحصول على birthday و phone)
                getAccessToken(account) { accessToken ->
                    // أرسل للـ backend
                    sendToBackend(idToken, accessToken)
                }
            }.addOnFailureListener { e ->
                Log.e("GoogleAuth", "Error: ${e.message}")
            }
        }
    }
    
    private fun getAccessToken(account: GoogleSignInAccount, callback: (String?) -> Unit) {
        // استخدم GoogleAuthUtil للحصول على access_token
        Thread {
            try {
                val scope = "oauth2:https://www.googleapis.com/auth/user.birthday.read https://www.googleapis.com/auth/user.phonenumbers.read"
                val accessToken = GoogleAuthUtil.getToken(
                    this,
                    account.email,
                    scope
                )
                runOnUiThread { callback(accessToken) }
            } catch (e: Exception) {
                Log.e("GoogleAuth", "Error getting access token: ${e.message}")
                runOnUiThread { callback(null) }
            }
        }.start()
    }
    
    private fun sendToBackend(idToken: String?, accessToken: String?) {
        val client = OkHttpClient()
        val json = JSONObject().apply {
            put("id_token", idToken)
            if (accessToken != null) {
                put("access_token", accessToken)
            }
        }
        
        val requestBody = json.toString().toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("https://your-backend.com/auth/google")
            .post(requestBody)
            .build()
        
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                Log.e("Backend", "Error: ${e.message}")
            }
            
            override fun onResponse(call: Call, response: Response) {
                val responseBody = response.body?.string()
                Log.d("Backend", "Response: $responseBody")
                // معالجة الاستجابة
            }
        })
    }
}
```

### Facebook Login مع جلب جميع البيانات

```kotlin
import com.facebook.AccessToken
import com.facebook.CallbackManager
import com.facebook.FacebookCallback
import com.facebook.FacebookException
import com.facebook.login.LoginManager
import com.facebook.login.LoginResult
import okhttp3.*
import org.json.JSONObject

class FacebookAuthActivity : AppCompatActivity() {
    
    private lateinit var callbackManager: CallbackManager
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        callbackManager = CallbackManager.Factory.create()
    }
    
    fun signInWithFacebook() {
        // ⚠️ مهم: طالب بالأذونات المطلوبة
        val permissions = listOf(
            "email",
            "public_profile",
            "user_birthday",        // للحصول على تاريخ الميلاد
            "user_phone_number"      // للحصول على رقم الهاتف
        )
        
        LoginManager.getInstance().logInWithReadPermissions(
            this,
            permissions
        )
        
        LoginManager.getInstance().registerCallback(callbackManager,
            object : FacebookCallback<LoginResult> {
                override fun onSuccess(result: LoginResult) {
                    val accessToken = result.accessToken.token
                    sendToBackend(accessToken)
                }
                
                override fun onCancel() {
                    Log.d("Facebook", "Login cancelled")
                }
                
                override fun onError(error: FacebookException) {
                    Log.e("Facebook", "Error: ${error.message}")
                }
            })
    }
    
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        callbackManager.onActivityResult(requestCode, resultCode, data)
    }
    
    private fun sendToBackend(accessToken: String) {
        val client = OkHttpClient()
        val json = JSONObject().apply {
            put("access_token", accessToken)
        }
        
        val requestBody = json.toString().toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("https://your-backend.com/auth/facebook")
            .post(requestBody)
            .build()
        
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                Log.e("Backend", "Error: ${e.message}")
            }
            
            override fun onResponse(call: Call, response: Response) {
                val responseBody = response.body?.string()
                Log.d("Backend", "Response: $responseBody")
                // معالجة الاستجابة
            }
        })
    }
}
```

---

## 🍎 iOS (Swift)

### Google Sign-In

```swift
import GoogleSignIn

class GoogleAuthViewController: UIViewController {
    
    func signInWithGoogle() {
        guard let clientID = Bundle.main.object(forInfoDictionaryKey: "GOOGLE_CLIENT_ID") as? String else {
            return
        }
        
        let config = GIDConfiguration(clientID: clientID)
        GIDSignIn.sharedInstance.configuration = config
        
        GIDSignIn.sharedInstance.signIn(withPresenting: self) { [unowned self] result, error in
            guard error == nil else {
                print("Error: \(error!.localizedDescription)")
                return
            }
            
            guard let user = result?.user,
                  let idToken = user.idToken?.tokenString else {
                return
            }
            
            // للحصول على access_token، تحتاج لاستخدام OAuth 2.0 flow
            // أو استخدم serverAuthCode
            let serverAuthCode = user.serverAuthCode
            
            // أرسل للـ backend
            sendToBackend(idToken: idToken, accessToken: nil)
        }
    }
    
    func sendToBackend(idToken: String, accessToken: String?) {
        let url = URL(string: "https://your-backend.com/auth/google")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        var body: [String: Any] = ["id_token": idToken]
        if let accessToken = accessToken {
            body["access_token"] = accessToken
        }
        
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                print("Error: \(error.localizedDescription)")
                return
            }
            
            if let data = data {
                let response = try? JSONSerialization.jsonObject(with: data)
                print("Response: \(response ?? "")")
            }
        }.resume()
    }
}
```

### Facebook Login

```swift
import FBSDKLoginKit

class FacebookAuthViewController: UIViewController {
    
    func signInWithFacebook() {
        let loginManager = LoginManager()
        
        // ⚠️ مهم: طالب بالأذونات المطلوبة
        loginManager.logIn(permissions: [
            "email",
            "public_profile",
            "user_birthday",
            "user_phone_number"
        ], from: self) { result, error in
            if let error = error {
                print("Error: \(error.localizedDescription)")
                return
            }
            
            guard let result = result, !result.isCancelled else {
                print("Login cancelled")
                return
            }
            
            if let accessToken = AccessToken.current?.tokenString {
                self.sendToBackend(accessToken: accessToken)
            }
        }
    }
    
    func sendToBackend(accessToken: String) {
        let url = URL(string: "https://your-backend.com/auth/facebook")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let body = ["access_token": accessToken]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                print("Error: \(error.localizedDescription)")
                return
            }
            
            if let data = data {
                let response = try? JSONSerialization.jsonObject(with: data)
                print("Response: \(response ?? "")")
            }
        }.resume()
    }
}
```

---

## 🌐 Web (JavaScript)

### Google Sign-In

```html
<!DOCTYPE html>
<html>
<head>
    <script src="https://accounts.google.com/gsi/client" async defer></script>
</head>
<body>
    <div id="g_id_onload"
         data-client_id="YOUR_CLIENT_ID"
         data-callback="handleCredentialResponse">
    </div>
    <div class="g_id_signin" data-type="standard"></div>

    <script>
        function handleCredentialResponse(response) {
            const idToken = response.credential;
            
            // للحصول على access_token، استخدم OAuth 2.0 flow
            // أو استخدم Google Sign-In JavaScript SDK
            getAccessToken(idToken);
        }
        
        function getAccessToken(idToken) {
            // استخدم Google Sign-In JavaScript SDK
            gapi.load('auth2', function() {
                gapi.auth2.init({
                    client_id: 'YOUR_CLIENT_ID'
                }).then(function() {
                    const authInstance = gapi.auth2.getAuthInstance();
                    authInstance.signIn({
                        scope: 'profile email https://www.googleapis.com/auth/user.birthday.read https://www.googleapis.com/auth/user.phonenumbers.read'
                    }).then(function(googleUser) {
                        const accessToken = googleUser.getAuthResponse().access_token;
                        sendToBackend(idToken, accessToken);
                    });
                });
            });
        }
        
        function sendToBackend(idToken, accessToken) {
            fetch('https://your-backend.com/auth/google', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    id_token: idToken,
                    access_token: accessToken
                })
            })
            .then(response => response.json())
            .then(data => {
                console.log('Success:', data);
            })
            .catch(error => {
                console.error('Error:', error);
            });
        }
    </script>
</body>
</html>
```

### Facebook Login

```html
<!DOCTYPE html>
<html>
<head>
    <script async defer crossorigin="anonymous" 
            src="https://connect.facebook.net/en_US/sdk.js"></script>
</head>
<body>
    <button onclick="loginWithFacebook()">Login with Facebook</button>

    <script>
        window.fbAsyncInit = function() {
            FB.init({
                appId: 'YOUR_APP_ID',
                cookie: true,
                xfbml: true,
                version: 'v18.0'
            });
        };

        function loginWithFacebook() {
            FB.login(function(response) {
                if (response.authResponse) {
                    const accessToken = response.authResponse.accessToken;
                    sendToBackend(accessToken);
                }
            }, {
                // ⚠️ مهم: طالب بالأذونات المطلوبة
                scope: 'email,public_profile,user_birthday,user_phone_number'
            });
        }
        
        function sendToBackend(accessToken) {
            fetch('https://your-backend.com/auth/facebook', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    access_token: accessToken
                })
            })
            .then(response => response.json())
            .then(data => {
                console.log('Success:', data);
                console.log('Data retrieved:', data.data_retrieved);
                console.log('Missing fields:', data.missing_fields);
            })
            .catch(error => {
                console.error('Error:', error);
            });
        }
    </script>
</body>
</html>
```

---

## 📝 ملاحظات مهمة

1. **Google**: 
   - `id_token` يعطيك: email, name, picture ✅
   - `access_token` إضافي يعطيك: birthday, phone_number ⚠️

2. **Facebook**:
   - `access_token` يعطيك كل البيانات المتاحة حسب الأذونات ✅
   - تأكد من طلب الأذونات: `user_birthday`, `user_phone_number` ⚠️

3. **التحقق من البيانات**:
   - شوف الـ response من الـ backend
   - حقل `data_retrieved` يخبرك شو وصل
   - حقل `missing_fields` يخبرك شو ناقص


