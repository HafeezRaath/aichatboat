from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import os
import base64
import uuid
from datetime import datetime, timedelta
import httpx

# ============ CONFIGURATION ============
SHOPIFY_SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN", "your-store.myshopify.com")
SHOPIFY_ADMIN_API_TOKEN = os.getenv("SHOPIFY_ADMIN_API_TOKEN", "")
SHOPIFY_STOREFRONT_ACCESS_TOKEN = os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")

# DO NOT auto-append .myshopify.com - user has custom domain
# Just ensure no trailing slash
SHOPIFY_SHOP_DOMAIN = SHOPIFY_SHOP_DOMAIN.rstrip('/')

print("=" * 60)
print("CONFIG LOADED:")
print("  SHOPIFY_SHOP_DOMAIN:", SHOPIFY_SHOP_DOMAIN)
print("  ADMIN_TOKEN set:", bool(SHOPIFY_ADMIN_API_TOKEN))
print("  STOREFRONT_TOKEN set:", bool(SHOPIFY_STOREFRONT_ACCESS_TOKEN))
print("  OPENAI_KEY set:", bool(OPENAI_API_KEY))
print("=" * 60)

app = FastAPI(title="REZON AI VTON Engine", version="1.0.0")

# ============ CORS ============
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ MOCK PRODUCTS (Fallback when Shopify API fails) ============
MOCK_PRODUCTS = [
    {
        "id": "gid://shopify/Product/1",
        "title": "Premium Unstitched Fabric - Grey",
        "description": "High quality unstitched fabric perfect for summer suits. Soft cotton blend with elegant texture.",
        "handle": "premium-unstitched-fabric-grey",
        "price": "5990.00",
        "compare_at_price": "7500.00",
        "currency": "PKR",
        "image_url": "https://cdn.shopify.com/s/files/1/placeholder-grey-fabric.jpg",
        "variant_id": "gid://shopify/ProductVariant/1"
    },
    {
        "id": "gid://shopify/Product/2",
        "title": "Wash & Wear - Black",
        "description": "Easy maintenance wash and wear fabric. Perfect for daily office wear and formal occasions.",
        "handle": "wash-wear-black",
        "price": "4950.00",
        "compare_at_price": "6200.00",
        "currency": "PKR",
        "image_url": "https://cdn.shopify.com/s/files/1/placeholder-black-fabric.jpg",
        "variant_id": "gid://shopify/ProductVariant/2"
    },
    {
        "id": "gid://shopify/Product/3",
        "title": "Summer Lawn Collection - Floral",
        "description": "Breathable lawn fabric with beautiful floral print. Ideal for hot summer days.",
        "handle": "summer-lawn-collection-floral",
        "price": "3990.00",
        "compare_at_price": "5500.00",
        "currency": "PKR",
        "image_url": "https://cdn.shopify.com/s/files/1/placeholder-lawn.jpg",
        "variant_id": "gid://shopify/ProductVariant/3"
    },
    {
        "id": "gid://shopify/Product/4",
        "title": "Luxury Perfume - Oud Collection",
        "description": "Premium oud fragrance with long lasting scent. Perfect for special occasions.",
        "handle": "luxury-perfume-oud",
        "price": "8500.00",
        "compare_at_price": "12000.00",
        "currency": "PKR",
        "image_url": "https://cdn.shopify.com/s/files/1/placeholder-perfume.jpg",
        "variant_id": "gid://shopify/ProductVariant/4"
    },
    {
        "id": "gid://shopify/Product/5",
        "title": "Leather Wallet - Brown",
        "description": "Genuine leather wallet with multiple card slots and coin pocket. Premium quality stitching.",
        "handle": "leather-wallet-brown",
        "price": "2950.00",
        "compare_at_price": "4200.00",
        "currency": "PKR",
        "image_url": "https://cdn.shopify.com/s/files/1/placeholder-wallet.jpg",
        "variant_id": "gid://shopify/ProductVariant/5"
    }
]

# ============ ROOT / HEALTH ============
@app.get("/")
async def root():
    return {"message": "REZON AI VTON Engine Running", "version": "1.0.0", "status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ============ SHOPIFY OAUTH ============
@app.get("/auth/callback")
async def shopify_callback(request: Request):
    code = request.query_params.get("code")
    shop = request.query_params.get("shop")
    if not code or not shop:
        return {"error": "Missing code or shop"}

    token_url = f"https://{shop}/admin/oauth/access_token"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            json={
                "client_id": SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
                "code": code
            }
        )
        data = response.json()

    access_token = data.get("access_token")
    print("=" * 60)
    print("SHOPIFY ACCESS TOKEN:", access_token)
    print("=" * 60)

    return {
        "success": True,
        "token": access_token,
        "shop": shop,
        "message": "Token captured! Copy this token to Railway variables."
    }

# ============ MODELS ============
class ChatMessage(BaseModel):
    role: str
    content: str
    product_cards: Optional[List[Dict]] = None
    image_url: Optional[str] = None

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: str
    product_context: Optional[str] = None

class SimpleChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"

class DiscountRequest(BaseModel):
    percentage: float = 5.0
    customer_email: Optional[str] = None
    product_id: Optional[str] = None

class VTONRequest(BaseModel):
    user_image_url: str
    product_image_url: str
    product_id: str
    session_id: str

class ProductFetchRequest(BaseModel):
    query: Optional[str] = None
    product_id: Optional[str] = None
    limit: int = 5

class AddToCartRequest(BaseModel):
    variant_id: str
    quantity: int = 1

# ============ SHOPIFY CLIENT ============
class ShopifyClient:
    def __init__(self, shop_domain: str, admin_token: str, storefront_token: str):
        self.shop_domain = shop_domain
        self.admin_url = f"https://{shop_domain}/admin/api/2024-07/graphql.json"
        self.storefront_url = f"https://{shop_domain}/api/2024-07/graphql.json"
        self.admin_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": admin_token
        }
        self.storefront_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": storefront_token
        }

    async def fetch_products(self, query: str = None, limit: int = 5) -> List[Dict]:
        # Check if storefront token is available
        if not self.storefront_headers["X-Shopify-Storefront-Access-Token"]:
            print("WARNING: SHOPIFY_STOREFRONT_ACCESS_TOKEN not set. Using mock products.")
            print("Please add SHOPIFY_STOREFRONT_ACCESS_TOKEN to Railway variables.")
            return MOCK_PRODUCTS[:limit]

        search_query = f"title:*{query}*" if query else ""

        graphql_query = """
        query getProducts($query: String, $limit: Int!) {
            products(first: $limit, query: $query) {
                edges {
                    node {
                        id
                        title
                        description
                        handle
                        priceRange {
                            minVariantPrice {
                                amount
                                currencyCode
                            }
                        }
                        images(first: 1) {
                            edges {
                                node {
                                    url
                                    altText
                                }
                            }
                        }
                        variants(first: 1) {
                            edges {
                                node {
                                    id
                                    price {
                                        amount
                                        currencyCode
                                    }
                                    compareAtPrice {
                                        amount
                                        currencyCode
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {"query": search_query, "limit": limit}

        try:
            print(f"Fetching products from: {self.storefront_url}")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.storefront_url,
                    headers=self.storefront_headers,
                    json={"query": graphql_query, "variables": variables},
                    timeout=10.0
                )

                print(f"Shopify API Status: {response.status_code}")
                print(f"Response length: {len(response.text)} chars")

                # Check if response is HTML (error page) instead of JSON
                if response.text.strip().startswith('<') or not response.text.strip():
                    print("ERROR: Shopify returned HTML/empty response instead of JSON.")
                    print("This usually means:")
                    print("  1. SHOPIFY_STOREFRONT_ACCESS_TOKEN is wrong/missing")
                    print("  2. Storefront API is not enabled")
                    print("  3. Domain is incorrect")
                    return MOCK_PRODUCTS[:limit]

                data = response.json()

            if "errors" in data:
                print("Shopify GraphQL errors:", data["errors"])
                return MOCK_PRODUCTS[:limit]

            products = []
            edges = data.get("data", {}).get("products", {}).get("edges", [])

            if not edges:
                print("No products found in Shopify store, using mock products")
                return MOCK_PRODUCTS[:limit]

            for edge in edges:
                node = edge["node"]
                variant = node["variants"]["edges"][0]["node"] if node["variants"]["edges"] else None
                image = node["images"]["edges"][0]["node"] if node["images"]["edges"] else None

                products.append({
                    "id": node["id"],
                    "title": node["title"],
                    "description": node.get("description", ""),
                    "handle": node["handle"],
                    "price": variant["price"]["amount"] if variant else "0.00",
                    "compare_at_price": variant["compareAtPrice"]["amount"] if variant and variant.get("compareAtPrice") else None,
                    "currency": variant["price"]["currencyCode"] if variant else "PKR",
                    "image_url": image["url"] if image else "",
                    "variant_id": variant["id"] if variant else None
                })

            print(f"Successfully fetched {len(products)} products from Shopify")
            return products

        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}")
            print("Response was not valid JSON. Using mock products.")
            return MOCK_PRODUCTS[:limit]
        except Exception as e:
            print(f"Error fetching products: {e}")
            return MOCK_PRODUCTS[:limit]

    async def create_cart(self, variant_id: str, quantity: int = 1) -> Dict:
        mutation = """
        mutation cartCreate($input: CartInput!) {
            cartCreate(input: $input) {
                cart {
                    id
                    checkoutUrl
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        variables = {
            "input": {
                "lines": [{"quantity": quantity, "merchandiseId": variant_id}]
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.storefront_url,
                    headers=self.storefront_headers,
                    json={"query": mutation, "variables": variables},
                    timeout=10.0
                )
                return response.json()
        except Exception as e:
            print(f"Error creating cart: {e}")
            return {"error": str(e)}

    async def create_discount_code(self, percentage: float = 5.0, prefix: str = "AI") -> Dict:
        code = f"{prefix}{uuid.uuid4().hex[:6].upper()}"

        mutation = """
        mutation discountCodeBasicCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
            discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                    id
                    codeDiscount {
                        ... on DiscountCodeBasic {
                            title
                            codes(first: 1) {
                                edges {
                                    node {
                                        code
                                    }
                                }
                            }
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        variables = {
            "basicCodeDiscount": {
                "title": f"AI Generated {percentage}% Off",
                "code": code,
                "startsAt": datetime.utcnow().isoformat() + "Z",
                "endsAt": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
                "customerSelection": {"all": True},
                "customerGets": {
                    "value": {"percentage": percentage},
                    "items": {"all": True}
                },
                "usageLimit": 1
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.admin_url,
                    headers=self.admin_headers,
                    json={"query": mutation, "variables": variables},
                    timeout=10.0
                )
                data = response.json()

            if data.get("data", {}).get("discountCodeBasicCreate", {}).get("userErrors"):
                errors = data["data"]["discountCodeBasicCreate"]["userErrors"]
                raise HTTPException(status_code=400, detail=errors)

            discount_node = data["data"]["discountCodeBasicCreate"]["codeDiscountNode"]
            return {
                "code": code,
                "percentage": percentage,
                "discount_id": discount_node["id"],
                "expires_at": variables["basicCodeDiscount"]["endsAt"]
            }
        except Exception as e:
            print(f"Error creating discount: {e}")
            raise HTTPException(status_code=500, detail=str(e))

shopify = ShopifyClient(SHOPIFY_SHOP_DOMAIN, SHOPIFY_ADMIN_API_TOKEN, SHOPIFY_STOREFRONT_ACCESS_TOKEN)

# ============ AI SERVICE ============
class AIService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.openai.com/v1/chat/completions"

    async def chat_with_products(self, messages: List[Dict], products: List[Dict] = None, force_products: bool = False) -> Dict:
        system_prompt = """You are REZON AI, a premium fashion assistant for a Shopify store called REZON. 
You help customers find products, provide styling advice, and recommend items from the store.

IMPORTANT RULES:
1. Always respond in Roman Urdu (Hinglish) if the customer uses it
2. When customer asks about products, ALWAYS use the show_products function
3. Be friendly, conversational, and helpful
4. Keep responses concise but informative
5. If products are available, mention them and offer to show them

Available product categories: Unstitched Fabric, Wash & Wear, Perfumes, Wallets, Gift Boxes"""

        formatted_messages = [{"role": "system", "content": system_prompt}]

        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
            else:
                role = msg.role
                content = msg.content

            if products and role == "user":
                content += f"\n\nAvailable Products: {json.dumps(products)}"
            formatted_messages.append({"role": role, "content": content})

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "show_products",
                    "description": "Show product cards to the user when they express interest in products, want to buy something, or ask what products are available",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Friendly message in Roman Urdu to accompany the products"
                            }
                        },
                        "required": ["message"]
                    }
                }
            }
        ]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": formatted_messages,
                        "tools": tools,
                        "tool_choice": "auto" if not force_products else {"type": "function", "function": {"name": "show_products"}},
                        "temperature": 0.7
                    },
                    timeout=30.0
                )

            result = response.json()

            if "choices" not in result:
                print("OpenAI error response:", result)
                return {"text": "Sorry, AI service temporarily unavailable. Please try again later.", "tool_calls": None}

            message = result["choices"][0]["message"]

            response_data = {
                "text": message.get("content", ""),
                "tool_calls": None
            }

            if message.get("tool_calls"):
                response_data["tool_calls"] = message["tool_calls"]

            return response_data

        except Exception as e:
            print("OpenAI API error:", str(e))
            return {"text": "Sorry, AI service mein masla hai. Thodi dair baad try karein.", "tool_calls": None}

ai_service = AIService(OPENAI_API_KEY)

# ============ API ROUTES ============

# ====== SIMPLE CHAT ======
@app.post("/api/chat-simple")
async def chat_simple(request: SimpleChatRequest):
    try:
        messages = [{"role": "user", "content": request.message}]

        # Check if user is asking about products
        product_keywords = ["product", "buy", "price", "dress", "shirt", "wallet", "kapra", "cheez", 
                           "suit", "clothes", "fashion", "len", "lena", "purchase", "dikhao", "show",
                           "lawn", "fabric", "perfume", "gift", "box", "wear", "unstitched", "dikhayo"]
        needs_products = any(kw in request.message.lower() for kw in product_keywords)

        products = []
        if needs_products:
            try:
                products = await shopify.fetch_products(limit=5)
            except Exception as e:
                print("Product fetch error:", e)
                products = MOCK_PRODUCTS[:5]

        ai_response = await ai_service.chat_with_products(messages, products, force_products=needs_products and len(products) > 0)

        # Check if AI wants to show products OR user asked for products
        tool_calls = ai_response.get("tool_calls")
        if (tool_calls and len(tool_calls) > 0) or needs_products:
            # Ensure we have products to show
            if len(products) == 0:
                products = MOCK_PRODUCTS[:5]

            return JSONResponse(content={
                "success": True,
                "response": ai_response.get("text") or "Yeh hain hamare best products!",
                "product_cards": products,
                "quick_replies": ["Fabrics dekhein", "Wallets explore karein", "Perfumes check karein", "Discount code chahiye"],
                "session_id": request.session_id
            })

        return JSONResponse(content={
            "success": True,
            "response": ai_response.get("text") or "Main aapki madad karne ke liye tayyar hoon!",
            "product_cards": None,
            "quick_replies": ["Products dekhein", "Styling tips chahiye", "Discount code"],
            "session_id": request.session_id
        })

    except Exception as e:
        print("Chat error:", str(e))
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "response": "Kuch galat ho gaya. Dobara try karein.", "error": str(e)}
        )

# ====== ADD TO CART ======
@app.post("/api/cart/add")
async def add_to_cart(request: AddToCartRequest):
    try:
        result = await shopify.create_cart(request.variant_id, request.quantity)

        if "error" in result:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Cart add failed", "error": result["error"]}
            )

        cart_data = result.get("data", {}).get("cartCreate", {})
        cart = cart_data.get("cart", {})

        return JSONResponse(content={
            "success": True,
            "cart_id": cart.get("id"),
            "checkout_url": cart.get("checkoutUrl"),
            "message": "Product cart mein add ho gaya!"
        })

    except Exception as e:
        print("Cart error:", str(e))
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Cart add failed", "error": str(e)}
        )

# ====== FULL CHAT ======
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        messages_dicts = []
        for msg in request.messages:
            messages_dicts.append({"role": msg.role, "content": msg.content})

        product_keywords = ["product", "buy", "price", "dress", "shirt", "wallet", "kapra", "cheez",
                           "suit", "clothes", "fashion", "len", "lena", "purchase", "dikhao", "show",
                           "lawn", "fabric", "perfume", "gift", "box", "wear", "unstitched", "dikhayo"]
        needs_products = any(kw in request.messages[-1].content.lower() for kw in product_keywords)

        products = []
        if needs_products:
            try:
                products = await shopify.fetch_products(limit=5)
            except Exception as e:
                print("Product fetch error:", e)
                products = MOCK_PRODUCTS[:5]

        ai_response = await ai_service.chat_with_products(messages_dicts, products, force_products=needs_products and len(products) > 0)

        tool_calls = ai_response.get("tool_calls")
        if (tool_calls and len(tool_calls) > 0) or needs_products:
            if len(products) == 0:
                products = MOCK_PRODUCTS[:5]

            return JSONResponse(content={
                "success": True,
                "response": ai_response.get("text") or "Yeh hain hamare best products!",
                "product_cards": products,
                "quick_replies": ["Fabrics dekhein", "Wallets explore karein", "Perfumes check karein", "Discount code chahiye"],
                "session_id": request.session_id
            })

        return JSONResponse(content={
            "success": True,
            "response": ai_response.get("text") or "Main aapki madad karne ke liye tayyar hoon!",
            "product_cards": None,
            "quick_replies": ["Products dekhein", "Styling tips chahiye", "Discount code"],
            "session_id": request.session_id
        })

    except Exception as e:
        print("Chat error:", str(e))
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/products")
async def get_products(request: ProductFetchRequest):
    try:
        products = await shopify.fetch_products(query=request.query, limit=request.limit)
        return {"success": True, "products": products}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/discount/generate")
async def generate_discount(request: DiscountRequest):
    try:
        discount = await shopify.create_discount_code(percentage=request.percentage, prefix="AI")
        return {
            "success": True,
            "discount": discount,
            "message": f"Aap ke liye {request.percentage}% discount code generate ho gaya hai!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/vton/process")
async def process_vton(request: VTONRequest):
    return {"success": True, "status": "processing", "message": "VTON processing started"}

@app.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        file_id = f"{uuid.uuid4()}_{file.filename}"
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, file_id)

        with open(file_path, "wb") as f:
            f.write(contents)

        return {
            "success": True,
            "url": f"/uploads/{file_id}",
            "file_id": file_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
